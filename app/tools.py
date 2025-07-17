# app/tools.py
from duckduckgo_search import DDGS
import structlog # MỚI: Import structlog

# MỚI: Khởi tạo logger cho module này
logger = structlog.get_logger(__name__)

def search_the_web(query: str, max_results: int = 3) -> str:
    """
    Thực hiện tìm kiếm web bằng DuckDuckGo và định dạng kết quả.
    Sử dụng structlog để ghi lại các sự kiện.
    """
    # THAY ĐỔI: Sử dụng logger thay vì print
    logger.info("Executing tool", tool_name="web_searcher", query=query)
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        
        if not results:
            logger.warning("Web search returned no results", query=query)
            return "Không tìm thấy kết quả nào trên web cho truy vấn này."

        formatted_results = []
        for i, result in enumerate(results):
            formatted_results.append(
                f"Nguồn [{i+1}]: {result.get('title', '')}\n"
                f"Nội dung: {result.get('body', '')}\n"
                f"Link: {result.get('href', '')}"
            )
        
        # THAY ĐỔI: Ghi log thành công
        logger.info("Web search successful", result_count=len(results))
        return "\n\n---\n\n".join(formatted_results)
        
    except Exception as e:
        # THAY ĐỔI: Ghi log lỗi với đầy đủ thông tin
        logger.error("Web search failed", error=str(e), exc_info=True)
        return "Đã xảy ra lỗi khi thực hiện tìm kiếm trên web."