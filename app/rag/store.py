# -*- coding: utf-8 -*-
"""知识库向量存储：把 knowledge/*.md 切块、嵌入、存入 Chroma，并提供检索。

企业级要点：
- 切块按 Markdown 标题边界切，保证每块语义完整（比固定字数硬切效果好）；
- 每块带元数据（来源文件、标题），检索结果可回溯出处——可溯源是客服合规的硬要求；
- ingest 是幂等的：同一次构建指纹相同就跳过，避免重复嵌入浪费钱/时间。
"""
import hashlib
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from app.core.config import settings

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"


def _embedder() -> SentenceTransformer:
    """懒加载嵌入模型（首次运行会从 HuggingFace 下载，之后走本地缓存）。"""
    return SentenceTransformer(settings.embedding_model)


def chunk_markdown(path: Path) -> list[dict]:
    """按 '## ' 标题把 Markdown 切成语义完整的块。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    chunks: list[dict] = []
    title = path.stem
    current: list[str] = []
    for line in lines:
        if line.startswith("## ") and current:
            chunks.append({"file": path.name, "section": title, "text": "\n".join(current).strip()})
            title = line.removeprefix("## ").strip()
            current = []
        current.append(line)
    if any(s.strip() for s in current):
        chunks.append({"file": path.name, "section": title, "text": "\n".join(current).strip()})
    return [c for c in chunks if c["text"]]


def build_fingerprint() -> str:
    """所有知识文件的联合指纹：文件内容变了才重建索引。"""
    h = hashlib.sha256()
    for p in sorted(KNOWLEDGE_DIR.glob("*.md")):
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def get_collection(client: chromadb.PersistentClient):
    return client.get_or_create_collection(
        "knowledge", metadata={"hnsw:space": "cosine"})


def ingest(force: bool = False) -> dict:
    """摄入全部知识文档。返回 {'status': 'rebuilt'|'skipped', 'chunks': N}。"""
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    col = get_collection(client)
    fp = build_fingerprint()

    if col.metadata and col.metadata.get("fingerprint") == fp and not force:
        return {"status": "skipped", "chunks": col.count()}
    if col.count():
        client.delete_collection("knowledge")
        col = get_collection(client)

    model = _embedder()
    docs: list[str] = []
    metas: list[dict] = []
    ids: list[str] = []
    for p in sorted(KNOWLEDGE_DIR.glob("*.md")):
        for i, c in enumerate(chunk_markdown(p)):
            docs.append(c["text"])
            metas.append({"file": c["file"], "section": c["section"]})
            ids.append(f"{c['file']}::{i}")
    embeddings = model.encode(docs, normalize_embeddings=True).tolist()
    col.add(documents=docs, embeddings=embeddings, metadatas=metas, ids=ids)
    col.modify(metadata={"fingerprint": fp})  # 距离函数创建时已定为 cosine，不能再改
    return {"status": "rebuilt", "chunks": len(docs)}


def retrieve(query: str, top_k: int = 4) -> list[dict]:
    """检索最相关的知识块，带相似度分数和出处。"""
    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    col = get_collection(client)
    if col.count() == 0:
        ingest()
    model = _embedder()
    q_emb = model.encode([query], normalize_embeddings=True).tolist()
    res = col.query(query_embeddings=q_emb, n_results=min(top_k, col.count()))
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({"text": doc, "file": meta["file"], "section": meta["section"],
                     "score": round(1 - dist, 4)})  # cosine distance -> similarity
    return hits
