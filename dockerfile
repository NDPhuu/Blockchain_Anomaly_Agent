# Bắt đầu từ một image Python chính thức, phiên bản slim để giữ kích thước nhỏ.
FROM python:3.11-slim

# Đặt thư mục làm việc bên trong container là /app.
# Tất cả các lệnh sau sẽ được thực thi từ thư mục này.
WORKDIR /app

# Cài đặt Poetry, công cụ quản lý thư viện của chúng ta.
# Đồng thời, cấu hình Poetry để không tạo môi trường ảo riêng bên trong Docker,
# vì Docker đã là một môi trường cô lập rồi.
RUN pip install poetry && poetry config virtualenvs.create false

# Tối ưu hóa Docker cache:
# Sao chép chỉ các file định nghĩa thư viện trước.
# Docker sẽ chỉ chạy lại bước cài đặt tốn thời gian ở dưới nếu các file này thay đổi.
COPY pyproject.toml poetry.lock* /app/

# Chạy lệnh cài đặt thư viện của Poetry.
# --no-root: Chỉ cài đặt các thư viện phụ thuộc, không cài đặt chính dự án này như một package.
#            Đây là bước quan trọng để giải quyết lỗi "README not found" mà chúng ta đã gặp.
# --no-interaction: Không hỏi bất kỳ câu hỏi tương tác nào.
# --no-ansi: Tắt các output màu mè, giúp log sạch hơn.
RUN poetry install --no-root --no-interaction --no-ansi

# Bây giờ, sao chép toàn bộ mã nguồn của ứng dụng vào container.
# Bước này được đặt sau bước cài đặt để tận dụng cache.
# Nếu bạn chỉ thay đổi code trong thư mục 'app', Docker sẽ không cần cài lại thư viện.
COPY ./app /app/app

# Lệnh sẽ được chạy khi container khởi động.
# Nó sẽ khởi chạy server Uvicorn, lắng nghe trên tất cả các địa chỉ IP ('0.0.0.0')
# và cổng 8000 bên trong container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]