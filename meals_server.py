"""TheMealDB MCP server. All diagnostics go to stderr through logging."""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from typing import Any

from hw5_tools.domain import retry_operation

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("meals_mcp")
BASE = "https://www.themealdb.com/api/json/v1/1"


def _get(path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    query = "?" + urllib.parse.urlencode(params or {}) if params else ""

    def request() -> dict[str, Any]:
        with urllib.request.urlopen(BASE + path + query, timeout=5) as response:
            import json
            return json.loads(response.read().decode("utf-8"))

    value, _, _ = retry_operation(request, attempts=3, timeout_seconds=5)
    return value


def _details(meal: dict[str, Any] | None) -> dict[str, Any]:
    if not meal:
        return {"message": "no matches"}
    ingredients = []
    for index in range(1, 21):
        name = (meal.get(f"strIngredient{index}") or "").strip()
        measure = (meal.get(f"strMeasure{index}") or "").strip()
        if name:
            ingredients.append({"name": name, "measure": measure})
    return {"id": meal.get("idMeal"), "name": meal.get("strMeal"), "category": meal.get("strCategory"),
            "area": meal.get("strArea"), "instructions": meal.get("strInstructions"),
            "image": meal.get("strMealThumb"), "source": meal.get("strSource"),
            "youtube": meal.get("strYoutube"), "ingredients": ingredients}


def search_meals_by_name(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(query, str) or not query.strip() or not 1 <= limit <= 25:
        raise ValueError("query must be non-empty and limit must be 1-25")
    meals = (_get("/search.php", {"s": query.strip()}).get("meals") or [])[:limit]
    return [{"id": m.get("idMeal"), "name": m.get("strMeal"), "area": m.get("strArea"),
             "category": m.get("strCategory"), "thumb": m.get("strMealThumb")} for m in meals]


def meals_by_ingredient(ingredient: str, limit: int = 12) -> list[dict[str, Any]]:
    if not isinstance(ingredient, str) or not ingredient.strip() or not 1 <= limit <= 25:
        raise ValueError("ingredient must be non-empty and limit must be 1-25")
    meals = (_get("/filter.php", {"i": ingredient.strip()}).get("meals") or [])[:limit]
    return [{"id": m.get("idMeal"), "name": m.get("strMeal"), "thumb": m.get("strMealThumb")} for m in meals]


def random_meal() -> dict[str, Any]:
    return _details((_get("/random.php").get("meals") or [None])[0])


def meal_details(id: str) -> dict[str, Any]:
    return _details((_get("/lookup.php", {"i": str(id)}).get("meals") or [None])[0])


try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

if FastMCP:
    mcp = FastMCP("meals")
    mcp.tool()(search_meals_by_name)
    mcp.tool()(meals_by_ingredient)
    mcp.tool()(random_meal)
    mcp.tool()(meal_details)
    if __name__ == "__main__":
        mcp.run(transport="stdio")
