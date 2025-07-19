# app/tools.py
import httpx
import structlog
from typing import Dict, Any
from duckduckgo_search import DDGS

# ==============================================================================
# Logger & Configuration
# ==============================================================================
logger = structlog.get_logger(__name__)

# Trong một hệ thống production thực tế, các URL này nên được quản lý 
# thông qua biến môi trường và Pydantic BaseSettings.
# Việc đặt chúng ở đây giúp dễ dàng cho việc phát triển ban đầu.
ANOMALY_SERVICE_URL = "https://fraudgraphml-2nz2.onrender.com/analyze"
GRAPH_SERVICE_URL = "https://fraudgraphml-2nz2.onrender.com/graph"

# ==============================================================================
# Công cụ Nghiệp vụ Cốt lõi (Core Business Tools)
# ==============================================================================

async def check_address_anomaly(address: str) -> str:
    """
    Gọi đến Anomaly Detection Service để kiểm tra một địa chỉ blockchain.
    Hàm này đã được cập nhật để sử dụng endpoint thật và xử lý các phản hồi lỗi cụ thể.
    """
    logger.info("Executing tool: anomaly_detector", address=address)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                ANOMALY_SERVICE_URL, 
                json={"address": address},
                timeout=20.0 # Tăng timeout một chút cho các dịch vụ trên render.com
            )
            
            # Không dùng raise_for_status() nữa vì API trả về 200 ngay cả khi có lỗi logic.
            # Thay vào đó, chúng ta kiểm tra nội dung JSON.
            data = response.json()

            # KIỂM TRA LỖI LOGIC TỪ API
            if "detail" in data:
                error_message = data["detail"]
                logger.warning("Anomaly Detection API returned a logical error", address=address, api_error=error_message)
                # Trả về thông báo lỗi thân thiện cho người dùng
                return f"Dịch vụ phân tích báo lỗi cho địa chỉ {address}: {error_message}"

            # XỬ LÝ KHI THÀNH CÔNG
            # Logic được điều chỉnh để khớp với output đã được ghi nhận: {"prediction": ..., "probability_fraud": ...}
            prediction = data.get('prediction', 'Không xác định')
            probability = data.get('probability_fraud', -1)
            
            # Chuyển đổi xác suất thành định dạng phần trăm dễ đọc
            if probability != -1:
                probability_percent = f"{probability:.2%}"
            else:
                probability_percent = "N/A"

            return (f"Kết quả phân tích bất thường cho địa chỉ {address}:\n"
                    f"- Đánh giá: {prediction}\n"
                    f"- Xác suất lừa đảo: {probability_percent}")

        except httpx.TimeoutException:
            logger.error("Timeout calling Anomaly Detection API", address=address)
            return f"Lỗi: Yêu cầu kiểm tra địa chỉ {address} đã hết thời gian chờ."
        except httpx.RequestError as e:
            logger.error("Anomaly detection API call failed", error=str(e), address=address)
            return f"Lỗi: Không thể kết nối đến dịch vụ phát hiện bất thường. Chi tiết: {e.request.url}"
        except Exception as e:
            logger.error("An unexpected error occurred in anomaly_detector", error=str(e), address=address, exc_info=True)
            return "Lỗi: Một lỗi không mong muốn đã xảy ra khi xử lý yêu cầu phát hiện bất thường."

async def analyze_address_graph(address: str) -> str:
    """
    Gọi đến Graph Handling Service để phân tích các mối quan hệ của một địa chỉ.
    """
    logger.info("Executing tool: graph_handler", address=address)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{GRAPH_SERVICE_URL}?address={address}",
                timeout=20.0 # Có thể cần timeout dài hơn cho các phân tích phức tạp
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Định dạng kết quả JSON thành một chuỗi văn bản súc tích.
            top_interactions = data.get('top_interactions', [])
            interaction_summary = "\n".join([f"  - {tx.get('type', 'N/A')} với {tx.get('counterparty', 'N/A')} ({tx.get('count', 0)} lần)" for tx in top_interactions]) or "Không có tương tác đáng chú ý."
            
            return (f"Kết quả phân tích quan hệ cho địa chỉ {address}:\n"
                    f"- Tổng số giao dịch đã phân tích: {data.get('total_transactions', 'N/A')}\n"
                    f"- Các tương tác chính nổi bật:\n{interaction_summary}\n"
                    f"- Tóm tắt hành vi tổng thể: {data.get('behavior_summary', 'Không có.')}")

        except httpx.TimeoutException:
            logger.error("Timeout calling Graph Handling API", address=address)
            return f"Lỗi: Yêu cầu phân tích đồ thị cho địa chỉ {address} đã hết thời gian chờ."
        except httpx.RequestError as e:
            logger.error("Graph handling API call failed", error=str(e), address=address)
            return f"Lỗi: Không thể kết nối đến dịch vụ phân tích đồ thị cho địa chỉ {address}. Chi tiết: {e.request.url}"
        except Exception as e:
            logger.error("An unexpected error occurred in graph_handler", error=str(e), address=address, exc_info=True)
            return "Lỗi: Một lỗi không mong muốn đã xảy ra khi xử lý yêu cầu phân tích đồ thị."

# ==============================================================================
# Công cụ Hiện có (Existing Tools)
# ==============================================================================

async def search_the_web_async(query: str) -> str:
    """
    Phiên bản bất đồng bộ của công cụ tìm kiếm web.
    """
    logger.info("Executing tool: web_searcher", query=query)
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=5)]
        
        if not results:
            return "Không tìm thấy kết quả nào trên web."
            
        return "\n\n---\n\n".join([f"Nguồn: {res['href']}\nNội dung: {res['body']}" for res in results])
    except Exception as e:
        logger.error("Web search failed", error=str(e), query=query)
        return "Lỗi: Không thể thực hiện tìm kiếm trên web."