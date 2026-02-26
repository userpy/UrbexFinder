import os
import sys
from decimal import Decimal, ROUND_DOWN

from jinja2 import Environment, FileSystemLoader
from typing import Optional


class TemplateRenderer:
    def __init__(self, template_dir: Optional[str] = None):
        if template_dir is None:
            main_dir = os.path.dirname(sys.modules["__main__"].__file__)
            template_dir = os.path.join(
                main_dir, "interface", "handlers", "templates"
            )

        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )

        # регистрация фильтров
        self.env.filters["human_distance"] = self.human_distance
        self.env.filters["cut_coord"] = self.cut_coord

    def human_distance(self, value: float | None) -> str | None:
        if value is None:
            return None

        meters = int(round(value * 1000))

        km = meters // 1000
        m = meters % 1000

        if km > 0 and m > 0:
            return f"{km} км {m} м"
        if km > 0:
            return f"{km} км"
        return f"{m} м"

    def cut_coord(self, value, digits=5):
        q = "0." + "0" * digits
        return Decimal(str(value)).quantize(Decimal(q), rounding=ROUND_DOWN)

    def render(self, template_name: str, params: dict) -> str:
        template = self.env.get_template(template_name)
        return template.render(**params)
