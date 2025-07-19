# app/agent_service.py
import json
import re # MỚI: Import thư viện regex
from typing import AsyncGenerator, List
from qdrant_client import QdrantClient
from qdrant_client.http.models import ScoredPoint
from sentence_transformers import SentenceTransformer
from sentence_transformers.cross_encoder import CrossEncoder
from langchain_community.chat_models.ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import structlog

# MỚI: Import module tools
from . import tools

# --- CẤU HÌNH ---
LLM_MODEL_NAME = "llama3:8b-instruct-q4_K_M"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "blockchain_knowledge"
CROSS_ENCODER_MODEL_NAME = 'cross-encoder/ms-marco-MiniLM-L-6-v2'
RETRIEVAL_CANDIDATE_COUNT = 10
FINAL_CONTEXT_COUNT = 3

logger = structlog.get_logger(__name__)

# MỚI: PROMPT NÂNG CẤP CHO ROUTER
ROUTER_PROMPT = """Bạn là một AI dispatcher cực kỳ thông minh và chính xác. Nhiệm vụ của bạn là phân tích câu hỏi của người dùng và chọn MỘT công cụ DUY NHẤT phù hợp nhất từ danh sách dưới đây. Bạn PHẢI trả lời bằng một chuỗi JSON hợp lệ.

**QUY TẮC BẮT BUỘC:**
- Nếu câu hỏi chứa một địa chỉ blockchain (ví dụ: 0x...), BẮT BUỘC phải ưu tiên chọn `anomaly_detector` hoặc `graph_handler`.
- KHÔNG được chọn `knowledge_base_retriever` nếu câu hỏi chứa một địa chỉ cụ thể để phân tích.
- Câu trả lời của bạn BẮT BUỘC chỉ được chứa duy nhất chuỗi JSON, không có bất kỳ văn bản, giải thích hay khối mã (```) nào khác.
**DANH SÁCH CÔNG CỤ:**

1. `anomaly_detector`:
   - Chức năng: Kiểm tra rủi ro, phân tích sự bất thường, hoặc đánh giá một địa chỉ ví/hợp đồng cụ thể. (Checks for risk, analyzes anomalies, or evaluates a specific wallet/contract address).
   - Khi nào sử dụng: BẮT BUỘC sử dụng khi người dùng hỏi về "rủi ro", "an toàn", "lừa đảo", "scam", "check", "kiểm tra" một địa chỉ cụ thể.
   - Ví dụ:
     - "kiểm tra ví 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B"
     - "phân tích rủi ro của hợp đồng 0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
     - "Hãy kiểm tra rủi ro của địa chỉ 0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae giúp tôi"
   - "query" nên là câu hỏi gốc của người dùng.

2. `graph_handler`:
   - Chức năng: Phân tích và vẽ biểu đồ mối quan hệ, luồng giao dịch của một địa chỉ. (Analyzes and visualizes the transaction graph of an address).
   - Khi nào sử dụng: Khi người dùng muốn biết một địa chỉ đã "tương tác với ai", "giao dịch với ai", "luồng tiền", hoặc yêu cầu "vẽ biểu đồ", "phân tích quan hệ".
   - Ví dụ:
     - "ví 0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B đã giao dịch với những ai?"
     - "vẽ biểu đồ tương tác của hợp đồng này"
   - "query" nên là câu hỏi gốc của người dùng.

3. `knowledge_base_retriever`:
   - Chức năng: Trả lời các câu hỏi chung, định nghĩa, khái niệm.
   - Khi nào sử dụng: CHỈ sử dụng cho các câu hỏi chung chung, không chứa địa chỉ cụ thể.
   - Ví dụ: "tấn công re-entrancy là gì?", "làm thế nào để phát hiện một rug pull?".
   - "query" nên là câu hỏi gốc của người dùng.

4. `web_searcher`:
   - Chức năng: Tìm kiếm thông tin mới, tin tức, giá cả.
   - Khi nào sử dụng: Cho các câu hỏi về sự kiện gần đây, dự án mới, thông tin không mang tính học thuật.
   - Ví dụ: "tin tức mới nhất về dự án ZKsync là gì?", "giá ETH hôm nay".
   - "query" nên là một cụm từ tìm kiếm được tối ưu hóa.

---
Câu hỏi của người dùng:
"{question}"

JSON Output:
"""

# MỚI: Hàm helper để trích xuất địa chỉ
def _extract_address(query: str) -> str | None:
    """
    Một helper đơn giản để trích xuất địa chỉ Ethereum bằng regex.
    """
    match = re.search(r'(0x[a-fA-F0-9]{40})', query)
    if match:
        return match.group(1)
    return None

class AgentService:
    def __init__(self, qdrant_client: QdrantClient):
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
        
        # THAY ĐỔI: Sử dụng prompt router mới và mạnh mẽ hơn
        self.router_prompt_template = ChatPromptTemplate.from_template(ROUTER_PROMPT)

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
        pairs = [[question, doc.payload['content']] for doc in valid_documents]

        if not pairs:
            return []

        scores = self.cross_encoder.predict(pairs)
        scores = [float(s) for s in scores]
        reranked_docs_with_scores = sorted(
            zip(valid_documents, scores), key=lambda x: x[1], reverse=True
        )
        return [doc.payload['content'] for doc, score in reranked_docs_with_scores]

    def _get_context_from_kb(self, question: str) -> str:
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
        logger.info("Agent execution started")

        # BƯỚC 1: ROUTER
        yield "Đang phân tích câu hỏi...\n"
        router_output_str = await self.router_chain.ainvoke({"question": question})
        
        tool_name = "knowledge_base_retriever"
        query = question

        try:
            # MỚI: Cố gắng tìm và trích xuất JSON từ bên trong khối mã
            match = re.search(r'\{.*\}', router_output_str, re.DOTALL)
            if match:
                json_str = match.group(0)
                router_output = json.loads(json_str)
            else:
                # Nếu không tìm thấy, thử phân tích chuỗi gốc
                router_output = json.loads(router_output_str)
            
            tool_name = router_output.get("tool", tool_name)
            query = router_output.get("query", question)
            logger.info("Router decision made", tool=tool_name, query=query)
        except json.JSONDecodeError:
            logger.warning("Router returned invalid JSON, falling back to default", 
                        invalid_json=router_output_str, 
                        fallback_tool=tool_name)

        # BƯỚC 2: EXECUTOR - THAY ĐỔI: Mở rộng hộp công cụ
        context = ""
        if tool_name == "anomaly_detector":
            address = _extract_address(query)
            if not address:
                context = f"Lỗi: Không thể trích xuất địa chỉ blockchain hợp lệ từ câu hỏi '{query}' để kiểm tra bất thường."
            else:
                yield "⏳ Đang kết nối tới dịch vụ phát hiện bất thường...\n"
                context = await tools.check_address_anomaly(address) # Phải dùng await

        elif tool_name == "graph_handler":
            # Đây là placeholder, chúng ta sẽ triển khai logic này ở bước tiếp theo
            yield "⏳ Chức năng phân tích đồ thị đang được phát triển...\n"
            context = "Lỗi: Chức năng phân tích đồ thị chưa được triển khai đầy đủ."

        elif tool_name == "web_searcher":
            yield "Đang tìm kiếm trên web...\n"
            # Giả định bạn đã cập nhật tools.py để có hàm async
            context = await tools.search_the_web_async(query) 

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