"""Copy public originals and already checked extracted text; never copy answer cards."""
from pathlib import Path
import csv
import hashlib
import json
import shutil


def main():
    source_dir = Path(__file__).resolve().parents[3] / "资料与内容"
    target = Path(__file__).resolve().parent / "seed_data"
    target.mkdir(parents=True, exist_ok=True)
    originals = target / "originals"
    originals.mkdir(exist_ok=True)
    records = []
    with (source_dir / "资料索引.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            source = Path(row["local_path"])
            raw = source.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            if row.get("sha256") and digest != row["sha256"]:
                raise RuntimeError("Public source hash mismatch: " + row["source_id"])
            destination = originals / source.name
            shutil.copy2(source, destination)
            text = Path(row["text_path"]).read_text(encoding="utf-8-sig")
            records.append({
                "id": row["source_id"], "title": row["title"], "publisher": row["publisher"],
                "url": row["url"], "published_at": row["published_at"],
                "period": row["study_period"], "kind": row["source_type"],
                "summary": row["supported_claim"], "scope_limit": row["scope_limit"],
                "locator": row["locator"], "origin": "prepared", "fetched_at": "2026-09-11",
                "text": text, "original_name": source.name, "original_sha256": digest,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "content_kind": "已核对的原文摘录/关键页" if "关键页" in row["text_path"] else "原文抽取文本",
            })
    (target / "sources.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"public_sources": len(records), "original_bytes": sum((originals / r["original_name"]).stat().st_size for r in records), "answer_cards_imported": False}))


if __name__ == "__main__":
    main()
