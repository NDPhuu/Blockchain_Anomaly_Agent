# app/vector_store_client.py
import os
from qdrant_client import QdrantClient

COLLECTION_NAME = "blockchain_knowledge"

class QdrantVectorStoreClient:
    def __init__(self):
        host = os.getenv("QDRANT_HOST", "localhost")
        # Qdrant client thông minh, nó sẽ tự xử lý các cổng. Chỉ cần cung cấp cổng REST.
        port = 6333
        
        print(f"Attempting to connect to Qdrant at: {host}:{port}")
        self.client = QdrantClient(host=host, port=port)
        print("Successfully initialized Qdrant client.")

    def check_connection(self):
        """Kiểm tra kết nối tới Qdrant server bằng cách lấy thông tin cluster."""
        try:
            # Đây là một lệnh chỉ đọc, an toàn để kiểm tra kết nối.
            self.client.get_collections()
            print("Qdrant connection check successful.")
            return True
        except Exception as e:
            print(f"Failed to connect to Qdrant: {e}")
            return False

db_client = QdrantVectorStoreClient()