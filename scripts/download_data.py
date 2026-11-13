# -*- coding: utf-8 -*-
"""M0 数据准备：下载 Olist 巴西电商公开数据集的 7 个 CSV 到 data/raw/。

数据来源：GitHub 镜像 spdrio/Brazilian-E-Commerce-Public-Dataset-by-Olist（Olist 官方
Kaggle 数据集的镜像，文件名一致）。已存在的文件跳过，可重复执行。
"""
from pathlib import Path
import urllib.request

BASE = Path(__file__).resolve().parents[1]
RAW = BASE / "data" / "raw"
BASE_URL = ("https://raw.githubusercontent.com/spdrio/"
            "Brazilian-E-Commerce-Public-Dataset-by-Olist/master/files/")

FILES = [
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_order_reviews_dataset.csv",
    "olist_products_dataset.csv",
    "olist_order_customer_dataset.csv",
    "product_category_name_translation.csv",
]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest = RAW / name
        if dest.exists() and dest.stat().st_size > 0:
            print(f"[skip] {name} 已存在")
            continue
        url = BASE_URL + name
        print(f"[down] {name} ...")
        try:
            urllib.request.urlretrieve(url, dest)
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"       OK ({size_mb:.1f} MB)")
        except Exception as e:
            print(f"       下载失败: {e}")
            print("       请手动从 Kaggle 'Brazilian E-Commerce Public Dataset by Olist' 下载同名文件放入 data/raw/")
    print("完成。下一步: python scripts/seed_db.py")


if __name__ == "__main__":
    main()
