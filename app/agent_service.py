# app/agent_service.py
import json
from typing import AsyncGenerator, List
from qdrant_client import QdrantClient
from qdrant_client.http.models import ScoredPoint
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from langchain_community.chat_models.ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import structlog # MỚI: Import structlog

# MỚI: Import module tools
from . import tools

# --- CẤU HÌNH ---
LLM_MODEL_NAME = "llama3:8b-instruct-q4_K_M"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "blockchain_knowledge"
CROSS_ENCODER_MODEL_NAME = 'cross-encoder/ms-marco-MiniLM-L-6-v2'
RETRIEVAL_CANDIDATE_COUNT = 10
FINAL_CONTEXT_COUNT = 3

# MỚI: Khởi tạo logger cho module này
logger = structlog.get_logger(__name__)

class AgentService:
    def __init__(self, qdrant_client: QdrantClient):
        # THAY ĐỔI: Sử dụng logger thay vì print
        logger.info("Initializing AgentService...")
        self.qdrant_client = qdrant_client
        
        logger.info("Loading models...", 
                    embedding_model=EMBEDDING_MODEL_NAME, 
                    cross_encoder_model=CROSS_ENCODER_MODEL_NAME)
        self.embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        self.cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL_NAME)
        
        self.llm = ChatOllama(
            base_url="http://host.docker.internal:11434",
            model=LLM_MODEL_NAME,
            temperature=0.1
        )
        
        self.router_prompt_template = ChatPromptTemplate.from_template(
            """Bạn là một AI router thông minh. Dựa vào câu hỏi của người dùng, nhiệm vụ của bạn là quyết định nên sử dụng công cụ nào để trả lời.
Hãy trả lời bằng một chuỗi JSON duy nhất và không thêm bất kỳ giải thích nào khác.

Đây là các công cụ có sẵn:
1. `knowledge_base_retriever`: Sử dụng công cụ này cho các câu hỏi liên quan đến kiến thức chuyên sâu về blockchain, các khái niệm kỹ thuật, phân tích các loại tấn công (ví dụ: Sybil, 51%), giải thích các thuật toán đồng thuận, hoặc các thông tin có trong tài liệu nội bộ.
2. `web_searcher`: Sử dụng công cụ này cho các câu hỏi về các sự kiện rất mới, tin tức, giá cả thị trường hiện tại, thông tin về các dự án blockchain cụ thể mà không có trong tài liệu, hoặc bất kỳ câu hỏi nào đòi hỏi kiến thức cập nhật từ thế giới thực.

Câu hỏi của người dùng:
"{question}"

Hãy tạo ra một chuỗi JSON với hai khóa: "tool" (tên công cụ được chọn) và "query" (truy vấn tìm kiếm, có thể là câu hỏi gốc hoặc một phiên bản được tối ưu hóa cho công cụ).

JSON Output:"""
        )

        self.synthesizer_prompt_template = ChatPromptTemplate.from_template(
            """Bạn là một trợ lý AI chuyên nghiệp, hữu ích.
Nhiệm vụ của bạn là trả lời câu hỏi của người dùng một cách ngắn gọn và chính xác.
Chỉ sử dụng những thông tin được cung cấp trong phần 'NGỮ CẢNH' dưới đây.
Nếu thông tin không có trong ngữ cảnh, hãy trả lời: "Tôi xin lỗi, tôi không tìm thấy thông tin về vấn đề này trong tài liệu của mình."
Tuyệt đối không được bịa đặt thông tin.

NGỮ CẢNH:
{context}

CÂU HỎI:
{question}

TRẢ LỜI:"""
        )
        
        self.router_chain = self.router_prompt_template | self.llm | StrOutputParser()
        self.synthesizer_chain = self.synthesizer_prompt_template | self.llm | StrOutputParser()
        
        logger.info("AgentService initialized successfully.")

    def _rerank_documents(self, question: str, documents: List[ScoredPoint]) -> List[str]:
        if not documents: return []
        valid_documents = [doc for doc in documents if doc.payload is not None and isinstance(doc.payload, dict) and 'content' in doc.payload and doc.payload['content'] is not None]
        if not valid_documents:
            return []
        pairs = []
        for doc in valid_documents:
            content = doc.payload.get('content') if isinstance(doc.payload, dict) else None
            if content is not None:
                pairs.append([question, content])
            else:
                pairs.append([question, ""])  # fallback to empty string if content missing

        if not pairs:
            return []

        scores = self.cross_encoder.predict(pairs)
        # Convert scores to a list of floats for sorting
        scores = [float(s) for s in scores]
        reranked_docs_with_scores = sorted(
            zip(valid_documents, scores), key=lambda x: x[1], reverse=True
        )
        result = []
        for doc, score in reranked_docs_with_scores:
            content = doc.payload.get('content') if isinstance(doc.payload, dict) else None
            if content is not None:
                result.append(content)
        return result

    def _get_context_from_kb(self, question: str) -> str:
        """
        Công cụ nội bộ: Truy vấn cơ sở tri thức Qdrant, re-rank và trả về context.
        """
        logger.info("Executing tool", tool_name="knowledge_base_retriever", query=question)
        query_vector = self.embedding_model.encode(question).tolist()
        
        search_results = self.qdrant_client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=RETRIEVAL_CANDIDATE_COUNT,
            with_payload=True
        )
        if not search_results:
            logger.warning("Knowledge base search returned no results", query=question)
            return "Không tìm thấy tài liệu nào trong cơ sở tri thức cho truy vấn này."

        reranked_docs = self._rerank_documents(question, search_results)
        final_docs = reranked_docs[:FINAL_CONTEXT_COUNT]
        if not final_docs:
            logger.warning("No relevant documents found after re-ranking", query=question)
            return "Không tìm thấy tài liệu liên quan sau khi xếp hạng lại."
            
        return "\n\n---\n\n".join(final_docs)

    async def execute_agent_stream(self, question: str) -> AsyncGenerator[str, None]:
        """
        Thực hiện chu trình Agent (Router -> Executor -> Synthesizer) và stream câu trả lời.
        """
        logger.info("Agent execution started")

        # BƯỚC 1: ROUTER
        yield "Đang phân tích câu hỏi...\n"
        router_output_str = await self.router_chain.ainvoke({"question": question})
        
        tool_name = "knowledge_base_retriever"
        query = question

        try:
            router_output = json.loads(router_output_str)
            tool_name = router_output.get("tool", tool_name)
            query = router_output.get("query", question)
            logger.info("Router decision made", tool=tool_name, query=query)
        except json.JSONDecodeError:
            logger.warning("Router returned invalid JSON, falling back to default", 
                           invalid_json=router_output_str, 
                           fallback_tool=tool_name)

        # BƯỚC 2: EXECUTOR
        context = ""
        if tool_name == "web_searcher":
            yield "Đang tìm kiếm trên web...\n"
            context = tools.search_the_web(query)
        elif tool_name == "knowledge_base_retriever":
            yield "Đang truy vấn cơ sở tri thức...\n"
            context = self._get_context_from_kb(query)
        else:
            logger.error("Router requested non-existent tool, falling back to default", 
                         requested_tool=tool_name,
                         fallback_tool="knowledge_base_retriever")
            yield f"Lỗi: Công cụ không tồn tại ('{tool_name}'). Đang sử dụng cơ sở tri thức mặc định...\n"
            context = self._get_context_from_kb(question)

        # BƯỚC 3: SYNTHESIZER
        yield "Đang tổng hợp câu trả lời...\n"
        
        context_snippet = (context[:250] + '...') if len(context) > 250 else context
        logger.info("Synthesizing final answer", context_snippet=context_snippet)
        
        async for chunk in self.synthesizer_chain.astream({"context": context, "question": question}):
            yield chunk
            
        logger.info("Agent stream finished.")