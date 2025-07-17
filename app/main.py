# app/main.py
import uuid
import time
from fastapi import FastAPI, Depends, HTTPException, Request # MỚI: Import Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
from typing import AsyncGenerator
import structlog # MỚI: Import structlog

# MỚI: Import hàm setup logging
from .logging_config import setup_logging
from .vector_store_client import db_client
from .agent_service import AgentService

# --- Global State ---
agent_service_instance: AgentService | None = None
# MỚI: Khởi tạo logger cho file main
logger = structlog.get_logger(__name__)

# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_service_instance
    
    # MỚI: Gọi hàm setup logging ngay khi ứng dụng khởi động
    setup_logging()
    
    logger.info("Application startup: Initializing services...")
    
    if not db_client.check_connection():
        logger.error("Fatal: Could not connect to Qdrant. Please check the service.")
        raise RuntimeError("Fatal: Could not connect to Qdrant. Please check the service.")
    logger.info("Qdrant connection verified.")
    
    agent_service_instance = AgentService(qdrant_client=db_client.client)
    
    yield
    
    logger.info("Application shutdown.")
    agent_service_instance = None

# --- App Instance ---
app = FastAPI(
    title="Streaming Agent Chatbot with Qdrant",
    description="Một chatbot Agent có khả năng streaming, chọn công cụ (RAG/Web Search), sử dụng FastAPI và Qdrant.",
    version="1.3.0", # Tăng phiên bản để phản ánh việc thêm logging
    lifespan=lifespan
)

# MỚI: Middleware để thêm request_id và log thông tin request
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    # Gán các biến context, chúng sẽ tự động được thêm vào tất cả các log của request này
    client_ip = request.client.host if request.client else "unknown"
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        client_ip=client_ip
    )
    
    start_time = time.time()
    logger.info("Request started", method=request.method, url=str(request.url))
    
    response = await call_next(request)
    
    process_time = (time.time() - start_time) * 1000
    logger.info(
        "Request finished",
        status_code=response.status_code,
        process_time_ms=f"{process_time:.2f}"
    )
    
    # Dọn dẹp context sau khi request kết thúc
    structlog.contextvars.clear_contextvars()
    return response

# --- API Models ---
class ChatRequest(BaseModel):
    question: str

# --- Dependency Injection ---
def get_agent_service() -> AgentService:
    if agent_service_instance is None:
        raise HTTPException(status_code=503, detail="Service not available.")
    return agent_service_instance

# --- API Endpoints ---
@app.get("/api/v1/health", tags=["Monitoring"])
def get_health():
    return {"status": "ok"}

@app.post("/api/v1/chat", tags=["Chat"])
async def post_chat_stream(
    request: ChatRequest,
    agent_service: AgentService = Depends(get_agent_service)
):
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
        
    try:
        # Gán câu hỏi vào context log để nó xuất hiện trong tất cả các log liên quan
        structlog.contextvars.bind_contextvars(user_question=request.question)
        
        token_generator: AsyncGenerator[str, None] = agent_service.execute_agent_stream(request.question)
        return StreamingResponse(token_generator, media_type="text/event-stream")

    except Exception as e:
        # Log lỗi với đầy đủ thông tin
        logger.error("Chat endpoint error", error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred.")