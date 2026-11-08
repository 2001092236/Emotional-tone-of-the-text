"""Один раз проверить публикацию GitHub Pages из независимой сети."""
from __future__ import annotations
import json
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

ROOT = "https://2001092236.github.io/Emotional-tone-of-the-text/"
TARGETS = {
    "": "html",
    "official-speeches.html": "html",
    "audit.html": "html",
    "rights.html": "html",
    "data/summary.json": "summary",
    "data/hf_speeches_full_2026.json": "speeches",
}

def validate(kind: str, payload: bytes) -> dict:
    if kind == "html":
        text = payload.decode("utf-8")
        if "<html" not in text.lower() or 'lang="ru"' not in text:
            raise ValueError("Не найдена русскоязычная HTML-страница")
        return {"type":"html","bytes":len(payload)}
    data = json.loads(payload)
    if kind == "summary":
        if data.get("year") != 2026 or data.get("total", 0) < 8462:
            raise ValueError("Неожиданный год или недостаточный объём корпуса")
        return {"type":"summary","documents":data["total"]}
    if kind == "speeches":
        if data.get("total_documents") != 221 or len(data.get("documents",[])) != 221:
            raise ValueError("Отсутствует выпуск 221 речи")
        if any(d.get("date","")[:4]!="2026" for d in data["documents"]):
            raise ValueError("Найдена речь вне 2026 года")
        return {"type":"speeches","documents":221}
    raise ValueError("Неизвестный тип источника")

def inspect(url: str, kind: str) -> dict:
    last_error = None
    for attempt in range(3):
        try:
            request=Request(url,headers={"User-Agent":"MGIMO-Public-Website-Health/1.0"})
            with urlopen(request,timeout=22) as resp:
                code, location=resp.status,resp.geturl()
                payload=resp.read(5_000_001)
            if code != 200 or not location.startswith(ROOT):
                raise ValueError(f"Неверный HTTP или редирект: {code} / {location}")
            if len(payload)>5_000_000:
                raise ValueError("Файл неожиданно большой")
            return validate(kind,payload)
        except (URLError,HTTPError,ValueError,OSError,UnicodeError,json.JSONDecodeError) as exc:
            last_error=exc
            if attempt<2:
                time.sleep(6)
    raise RuntimeError(f"{type(last_error).__name__}: {last_error}")

def main() -> int:
    problems=0
    for relative,kind in TARGETS.items():
        url=ROOT+relative
        try:
            print("OK",url,json.dumps(inspect(url,kind),ensure_ascii=False))
        except Exception as exc:
            problems+=1
            print("FAIL",url,exc,file=sys.stderr)
    return int(problems>0)

if __name__=="__main__":
    sys.exit(main())
