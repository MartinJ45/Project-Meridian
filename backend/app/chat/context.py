"""Per-turn state: what the UI should open and a trace of what the turn did."""
from dataclasses import dataclass, field

from .. import knowledge as kb


@dataclass
class TurnContext:
    con: object
    attachments: list = field(default_factory=list)
    trace: list = field(default_factory=list)

    def attach_document(self, doc_id: str) -> None:
        if any(a["document_id"] == doc_id and a["type"] == "drawing" for a in self.attachments):
            return
        doc = kb.get_document(self.con, doc_id)
        if not doc:
            return
        self.attachments.append({"type": "drawing", "document_id": doc_id, "title": doc["title"],
                                 "url": doc["file_url"], "distribution": doc["distribution"]})
        if doc["model"]:
            self.attachments.append({"type": "model3d", "document_id": doc_id, "title": doc["title"],
                                     "url": doc["model"]["url"], "label": doc["model"]["label"]})

    def log(self, step: str, args: dict, result):
        self.trace.append({"tool": step, "args": args, "result_preview": str(result)[:300]})
        return result
