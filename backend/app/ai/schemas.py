"""Shape of the AI answer (structured output: the model must return exactly this)."""

from pydantic import BaseModel, Field


class ManagerFinding(BaseModel):
    manager: str = Field(description="Псевдоним менеджера ровно как во входных данных, например «Менеджер-12»")
    summary: str = Field(description="1–2 предложения: как отработал период, с опорой на цифры")
    strengths: list[str] = Field(description="Что получилось, 0–3 пункта")
    problems: list[str] = Field(description="Проблемы с цифрами, 0–4 пункта")
    actions: list[str] = Field(description="Конкретные действия на следующий период, 1–3 пункта")


class RepeatedProblem(BaseModel):
    problem: str = Field(description="Проблема, которая повторяется: в нескольких периодах или у нескольких менеджеров")
    who: list[str] = Field(description="Псевдонимы менеджеров или «отдел»")
    evidence: str = Field(description="На каких цифрах или прошлых выводах это видно")


class Communication(BaseModel):
    assessed: bool = Field(description="true, только если во входных данных есть тексты комментариев или переписки")
    comments: list[str] = Field(description="Качество комментариев в карточках: форма «Дата/Цель/Итог/Следующий шаг», полнота")
    avito_replies: list[str] = Field(description="Качество ответов клиентам в Avito: скорость, вежливость, вопросы, следующий шаг")
    script: list[str] = Field(description="Соответствие скрипту продаж; пусто, если скрипт не передан")
    examples: list[str] = Field(description="2–4 коротких примера с номером сделки или чата: что не так и как лучше")


class PeriodAnalysis(BaseModel):
    headline: str = Field(description="Главный вывод периода одним-двумя предложениями")
    department: list[str] = Field(description="Выводы по отделу, 3–6 пунктов, каждый с цифрой и сравнением с прошлым периодом")
    risks: list[str] = Field(description="Риски для плана и сделок, 0–4 пункта")
    managers: list[ManagerFinding]
    repeated_problems: list[RepeatedProblem]
    communication: Communication
    recommendations: list[str] = Field(description="Что сделать руководителю, 2–5 пунктов, по приоритету")
