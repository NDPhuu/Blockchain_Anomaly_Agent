# app/logging_config.py
import logging
import sys
import structlog
from structlog.types import Processor

def setup_logging():
    """
    Thiết lập hệ thống logging có cấu trúc cho toàn bộ ứng dụng.
    """
    # Các "bộ xử lý" (processors) định nghĩa cách mỗi bản ghi log được xây dựng.
    # Chúng được thực thi theo thứ tự, giống như một pipeline.
    shared_processors: list[Processor] = [
        # 1. Thêm thông tin context (ví dụ: request_id) vào bản ghi.
        structlog.contextvars.merge_contextvars,
        # 2. Thêm thông tin về nơi gọi log (tên file, dòng, hàm).
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        # 3. Thêm timestamp.
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            # 4. Chuẩn bị bản ghi để có thể được xử lý bởi logging tiêu chuẩn của Python.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        # Cấu hình này giúp structlog "nói chuyện" được với logging tiêu chuẩn.
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Cấu hình formatter để render log cuối cùng.
    # Chúng ta sẽ sử dụng JSONRenderer để tạo ra các log có cấu trúc.
    formatter = structlog.stdlib.ProcessorFormatter(
        # Processor này sẽ render bản ghi log thành một chuỗi JSON.
        processor=structlog.processors.JSONRenderer(),
        # Giữ lại các trường đã được thêm bởi các processor ở trên.
        foreign_pre_chain=shared_processors,
    )

    # Thiết lập handler để ghi log ra console (stdout).
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Lấy root logger và thêm handler vào.
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO) # Đặt mức log tối thiểu là INFO.

    print("✅ Structured logging setup complete. Logs will be in JSON format.")