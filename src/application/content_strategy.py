from abc import ABC, abstractmethod
from src.domain.entities import Topic


class ContentGenerationStrategy(ABC):
    @abstractmethod
    def build_system_prompt(self) -> str:
        ...

    @abstractmethod
    def build_user_prompt(self, topic: Topic) -> str:
        ...

    @property
    @abstractmethod
    def style_guide(self) -> str:
        ...


class TutorialStrategy(ContentGenerationStrategy):
    @property
    def style_guide(self) -> str:
        return (
            "Write a step-by-step tutorial. Use numbered steps, code examples, "
            "and practical instructions. Assume the reader is a developer with basic knowledge."
        )

    def build_system_prompt(self) -> str:
        return (
            "You are an expert technical writer creating a developer tutorial. "
            "Write clear, actionable content with code snippets and practical examples. "
            "Include a compelling hook, step-by-step instructions, and a conclusion. "
            "Naturally incorporate relevant product references where appropriate. "
            "CRITICAL RULES: "
            "1) NEVER start with a heading (no # at the top). "
            "2) NEVER start with bold text (no ** at the top). "
            "3) NEVER repeat the topic/title at the beginning. "
            "4) Start with a plain paragraph introduction hook."
        )

    def build_user_prompt(self, topic: Topic) -> str:
        return (
            f"Write a detailed developer tutorial about: {topic.name}\n\n"
            f"Description: {topic.description}\n"
            f"Keywords to cover: {', '.join(topic.keywords)}\n\n"
            f"{self.style_guide}\n\n"
            f"Format the response as a complete markdown article body (no front matter). "
            f"Include code blocks, headings for sections, and practical examples. "
            f"DO NOT include any heading or bold text before the first paragraph. "
            f"Start with a plain text introduction hook."
        )


class OpinionStrategy(ContentGenerationStrategy):
    @property
    def style_guide(self) -> str:
        return (
            "Write an opinion piece that takes a clear stance. Use personal experience, "
            "industry observations, and data to support arguments. Be engaging and thought-provoking."
        )

    def build_system_prompt(self) -> str:
        return (
            "You are a thoughtful technology blogger sharing well-reasoned opinions. "
            "Write engaging, persuasive content that sparks discussion. "
            "Back claims with reasoning and real-world examples. "
            "CRITICAL RULES: "
            "1) NEVER start with a heading (no # at the top). "
            "2) NEVER start with bold text (no ** at the top). "
            "3) NEVER repeat the topic/title at the beginning. "
            "4) Start with a plain paragraph hook."
        )

    def build_user_prompt(self, topic: Topic) -> str:
        return (
            f"Write an opinion article about: {topic.name}\n\n"
            f"Context: {topic.description}\n"
            f"Keywords: {', '.join(topic.keywords)}\n\n"
            f"{self.style_guide}\n\n"
            f"Format the response as a complete markdown article body (no front matter). "
            f"Take a clear position and support it with reasoning. "
            f"DO NOT include any heading or bold text before the first paragraph. "
            f"Start with a plain text engaging hook."
        )


class HowToStrategy(ContentGenerationStrategy):
    @property
    def style_guide(self) -> str:
        return (
            "Write a practical how-to guide. Focus on solving a specific problem. "
            "Include prerequisites, step-by-step instructions, and expected outcomes."
        )

    def build_system_prompt(self) -> str:
        return (
            "You are a technical writer creating practical how-to guides. "
            "Focus on clarity, brevity, and actionable steps. "
            "Help the reader solve a specific problem efficiently. "
            "CRITICAL RULES: "
            "1) NEVER start with a heading (no # at the top). "
            "2) NEVER start with bold text (no ** at the top). "
            "3) NEVER repeat the topic/title at the beginning. "
            "4) Start with a plain paragraph problem statement."
        )

    def build_user_prompt(self, topic: Topic) -> str:
        return (
            f"Write a how-to guide for: {topic.name}\n\n"
            f"Problem: {topic.description}\n"
            f"Keywords: {', '.join(topic.keywords)}\n\n"
            f"{self.style_guide}\n\n"
            f"Format the response as a complete markdown article body (no front matter). "
            f"List prerequisites, provide clear steps, and show expected results. "
            f"DO NOT include any heading or bold text before the first paragraph. "
            f"Start with a plain text problem statement."
        )


class ContentStrategyFactory:
    _strategies = {
        "tutorial": TutorialStrategy,
        "opinion": OpinionStrategy,
        "howto": HowToStrategy,
    }

    @classmethod
    def create(cls, strategy_type: str) -> ContentGenerationStrategy:
        strategy_class = cls._strategies.get(strategy_type.lower())
        if not strategy_class:
            raise ValueError(f"Unknown strategy: {strategy_type}. Available: {list(cls._strategies.keys())}")
        return strategy_class()

    @classmethod
    def available_strategies(cls) -> list[str]:
        return list(cls._strategies.keys())
