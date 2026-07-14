#!/usr/bin/env python3
"""
FUSEキャッシュをバイパスしてWindowsフォルダのファイルを最新状態で読む。
O_DIRECTフラグを使いページキャッシュを経由しない。

使い方:
    from fresh_read import read_fresh, read_fresh_json
    text = read_fresh("/sessions/.../mnt/印西ニュース/news.json")
    data = read_fresh_json("/sessions/.../mnt/印西ニュース/news.json")
"""
import os, json

def read_fresh(path: str) -> str:
    """O_DIRECTでファイルを読み、文字列で返す"""
    fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
    try:
        chunks = []
        buf = bytearray(4096)
        view = memoryview(buf)
        while True:
            n = os.readv(fd, [view])
            if n == 0:
                break
            chunks.append(bytes(buf[:n]))
    finally:
        os.close(fd)
    return b"".join(chunks).decode("utf-8")

def read_fresh_json(path: str):
    """O_DIRECTでJSONファイルを読み、Pythonオブジェクトで返す"""
    return json.loads(read_fresh(path))

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("使い方: python fresh_read.py <ファイルパス>")
        sys.exit(1)
    print(read_fresh(path))
