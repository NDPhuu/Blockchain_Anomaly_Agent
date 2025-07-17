# scripts/ingest_data.py
import os
import glob
import uuid
import pandas as pd
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from langchain.text_splitter import RecursiveCharacterTextSplitter

# --- CẤU HÌNH ---
KNOWLEDGE_BASE_DIR = "knowledge_base"
COLLECTION_NAME = "blockchain_knowledge"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
# Kích thước vector của mô hình 'all-MiniLM-L6-v2' là 384. Đây là thông số BẮT BUỘC.
VECTOR_SIZE = 384

# --- KHỞI TẠO CLIENT VÀ MODEL ---
# Script này chạy trên host, kết nối qua localhost và cổng đã map
client = QdrantClient(host="localhost", port=6333)
# Tải mô hình embedding một lần và tái sử dụng
embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

def setup_collection():
    """Kiểm tra và tạo collection nếu chưa tồn tại."""
    print(f"Setting up collection: '{COLLECTION_NAME}'")
    try:
        client.get_collection(collection_name=COLLECTION_NAME)
        print("Collection already exists.")
    except Exception:
        print("Collection not found. Creating a new one...")
        client.recreate_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE),
        )
        print("Collection created successfully.")

def load_and_chunk_documents(directory: str) -> list[dict]:
    """Tải và chia nhỏ tài liệu."""
    documents = []
    # Tải file .md và .csv
    for file_path in glob.glob(os.path.join(directory, "*.md")):
        with open(file_path, 'r', encoding='utf-8') as f:
            documents.append({"content": f.read(), "source": os.path.basename(file_path)})
    for file_path in glob.glob(os.path.join(directory, "*.csv")):
        df = pd.read_csv(file_path)
        for _, row in df.iterrows():
            documents.append({"content": ", ".join(f"{k}: {v}" for k, v in row.items()), "source": os.path.basename(file_path)})

    # Chia nhỏ tài liệu
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = []
    for doc in documents:
        split_contents = text_splitter.split_text(doc["content"])
        for split in split_contents:
            chunks.append({"content": split, "source": doc["source"]})
    print(f"Loaded and chunked {len(documents)} documents into {len(chunks)} chunks.")
    return chunks

def embed_and_store_chunks(chunks: list[dict]):
    """Tạo embedding và lưu trữ các chunk vào Qdrant."""
    print(f"Embedding {len(chunks)} chunks...")
    
    # Lấy nội dung của tất cả các chunk để tạo embedding hàng loạt (rất hiệu quả)
    contents_to_embed = [chunk["content"] for chunk in chunks]
    vectors = embedding_model.encode(contents_to_embed, show_progress_bar=True)
    
    print("Storing points in Qdrant...")
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=str(uuid.uuid4()),  # Tạo ID ngẫu nhiên cho mỗi điểm
                vector=vector.tolist(), # Chuyển vector numpy thành list
                payload=chunk, # Payload chứa nội dung gốc và nguồn
            )
            for vector, chunk in zip(vectors, chunks)
        ],
        wait=True, # Chờ cho đến khi quá trình upsert hoàn tất
    )
    print("Successfully stored chunks in Qdrant.")

def main():
    """Hàm chính điều phối toàn bộ quá trình."""
    print("--- Starting Data Ingestion Pipeline for Qdrant ---")
    setup_collection()
    chunks = load_and_chunk_documents(KNOWLEDGE_BASE_DIR)
    if not chunks:
        print("No chunks to process. Exiting.")
        return
    embed_and_store_chunks(chunks)
    print("--- Data Ingestion Pipeline Finished ---")

if __name__ == "__main__":
    main()