"""Request/response models for the agent's /generate endpoint.

This is the contract between the backend and the agent. The backend sends the
conversation; the agent returns the model's reply text. Kept deliberately
minimal — no conversation ids, no sessions. Those are the backend's job.
"""

from pydantic import BaseModel


class Message(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class GenerateRequest(BaseModel):
    messages: list[Message]


class GenerateResponse(BaseModel):
    text: str
