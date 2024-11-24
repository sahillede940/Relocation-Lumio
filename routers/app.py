from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.future import select
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, List
from db import get_db
from Models.models import CityMetrics
from utils.query_data import query_rag
import requests
import openai
import os
openai.api_key = os.getenv("OPENAI_API_KEY")


# Create the router
api_router = APIRouter()


# Pydantic models for request validation
class CityRequest(BaseModel):
    id: int
    zip_code: Optional[str] = None
    city: Optional[str] = None
    state_code: Optional[str] = None
    state_name: Optional[str] = None


class QueryRequest(BaseModel):
    from_city: Optional[CityRequest] = None
    to_city: Optional[CityRequest] = None


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    city: Optional[str] = None


@api_router.get("/get-cities-list")
async def get_items_list(
    q: Optional[str] = Query(
        None, description="City name, state name, or zip code to search"
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for cities based on city name, state name, or zip code
    and return the top 10 matching results.
    """
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search term is required.")

    search_query = f"%{q.strip()}%"
    is_digit = q.isdigit()  # Check if the search term is numeric (zip code)

    # Perform query using SQLAlchemy
    query = select(CityMetrics).filter(
        or_(
            CityMetrics.city.ilike(search_query),
            CityMetrics.state_name.ilike(search_query),
            CityMetrics.zip_code.ilike(search_query) if is_digit else False,
        )
    ).limit(10)

    result = db.execute(query)
    cities = result.scalars().all()  # Correctly fetch all matching cities

    # If no results found
    if not cities:
        return {
            "results": [],
            "success": False,
            "message": "No matching cities found.",
        }

    # Prepare response
    return {
        "results": [
            {
                "id": city.id,
                "zip_code": city.zip_code,
                "city": city.city,
                "state_name": city.state_name,
                "state_code": city.state_code,
                "value": f"{city.city}, {city.state_code}{f' ({city.zip_code})' if is_digit else ''}",
            }
            for city in cities
        ],
        "success": True,
    }


def compare_cities(city1, city2):
    def extract_numeric(value):
        """Helper function to extract numeric values from strings with units or symbols."""
        return float(value.replace("$", "").replace("K", "000").replace("M", "000000").replace("B", "000000000").replace(",", "").replace(" ", "").strip())

    def calculate_normalized_percentage(city1_value, city2_value, is_higher_better=True):
        """Calculates normalized percentage difference between two values."""
        try:
            city1_value = extract_numeric(city1_value)
            city2_value = extract_numeric(city2_value)
            # Avoid division by zero or over-penalizing differences
            diff = abs(city2_value - city1_value)
            total = city1_value + city2_value
            percentage = (diff / total * 100) if total != 0 else 0
            return percentage if is_higher_better else -percentage
        except ValueError:
            return 0  # Handle missing or non-numeric data gracefully

    # Calculate normalized metrics with positive framing
    housing_affordability = (
        100 - calculate_normalized_percentage(
            city1["home_price"], city2["home_price"], is_higher_better=False)
        + calculate_normalized_percentage(
            city1["property_tax"], city2["property_tax"], is_higher_better=False)
        + calculate_normalized_percentage(
            city1["home_appreciation_rate"], city2["home_appreciation_rate"])
    ) / 3

    quality_of_life = (
        calculate_normalized_percentage(city1["education"], city2["education"])
        + calculate_normalized_percentage(
            city1["healthcare_fitness"], city2["healthcare_fitness"])
        + calculate_normalized_percentage(city1["weather_grade"], city2["weather_grade"])
        + 100 - calculate_normalized_percentage(
            city1["air_quality_index"], city2["air_quality_index"], is_higher_better=False)
        + calculate_normalized_percentage(
            city1["culture_entertainment"], city2["culture_entertainment"])
    ) / 5

    job_market_strength = (
        100 - calculate_normalized_percentage(
            city1["unemployment_rate"], city2["unemployment_rate"], is_higher_better=False)
        + calculate_normalized_percentage(city1["recent_job_growth"], city2["recent_job_growth"])
        + calculate_normalized_percentage(
            city1["future_job_growth_index"], city2["future_job_growth_index"])
    ) / 3

    living_affordability = (
        100 - calculate_normalized_percentage(
            city1["state_income_tax"], city2["state_income_tax"], is_higher_better=False)
        + 100 - calculate_normalized_percentage(
            city1["sales_tax"], city2["sales_tax"], is_higher_better=False)
        + 100 - calculate_normalized_percentage(
            city1["utilities"], city2["utilities"], is_higher_better=False)
        + 100 - calculate_normalized_percentage(
            city1["transportation_cost"], city2["transportation_cost"], is_higher_better=False)
    ) / 4

    # Calculate overall score
    overall_city_score = (
        housing_affordability + quality_of_life +
        job_market_strength + living_affordability
    ) / 4

    # Highlight strengths instead of direct scoring
    strengths = {
        "housing_affordability": "City 1" if housing_affordability > 50 else "City 2",
        "quality_of_life": "City 1" if quality_of_life > 50 else "City 2",
        "job_market_strength": "City 1" if job_market_strength > 50 else "City 2",
        "living_affordability": "City 1" if living_affordability > 50 else "City 2",
    }

    # Construct the response JSON
    response = {
        "housing_affordability": round(housing_affordability, 2),
        "quality_of_life": round(quality_of_life, 2),
        "job_market_strength": round(job_market_strength, 2),
        "living_affordability": round(living_affordability, 2),
        "overall_city_score": round(overall_city_score, 2),
        "strengths": strengths,
    }

    return response


@api_router.post("/comparison")
async def handle_query(request: QueryRequest, db: AsyncSession = Depends(get_db)):
    """
    Compare metrics between two cities.
    """
    # Validate input
    if not request.from_city or not request.to_city:
        raise HTTPException(
            status_code=400, detail="Both from_city and to_city are required."
        )

    # Fetch result from RAG function
    # result = {}
    result = query_rag(request.from_city.city, request.to_city.city)
    result["heading"] = {
        "title": "BIG MOVE!",
        "description": f"A move from {request.from_city.city} to {request.to_city.city} covers a significant distance. This move would bring substantial changes in cost of living, climate, and urban environment.",
    }

    # Fetch city data from the database
    city_1_data = db.execute(select(CityMetrics).filter(
        CityMetrics.zip_code == request.from_city.zip_code)).scalar_one_or_none()

    city_2_data = db.execute(select(CityMetrics).filter(
        CityMetrics.zip_code == request.to_city.zip_code)).scalar_one_or_none()

    # Check if city data exists
    if not city_1_data or not city_2_data:
        raise HTTPException(
            status_code=404, detail="City data not found for one or both cities."
        )

    return {
        **result,
        "city_1": city_1_data.__dict__,
        "city_2": city_2_data.__dict__,
        "comparison": compare_cities(city_1_data.__dict__, city_2_data.__dict__),
    }


@api_router.get("/similar_posts")
async def get_similar_posts(
    city: Optional[str] = Query(
        None, description="Search term to find similar posts"
    ),
):
    """
    Get similar posts based on the search term.
    """
    if not city:
        raise HTTPException(status_code=400, detail="Search term is required.")
    
    # replace space with + for the search query
    city = city.replace(" ", "+")

    data = requests.get(
        f"https://www.gayrealestate.com/blog/wp-json/wp/v2/posts?search={city}").json()
    # return top 3
    data = data[:3]
    return {
        "results": data,
        "success": True,
    }


def chat_with_gpt(messages: List[Message], city: str):
    """Send a prompt to OpenAI GPT-4 model and return the response."""
    try:
        system_prompt = f"You are an AI chatbot who is expert on LGBTQ+ related topics. Provide quick, concise, and helpful answers not more than 300 chars about LGBTQ+ resources, events, and information in {city}."

        messages = [{"role": "system", "content": system_prompt}] + messages

        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        return response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")


@api_router.post("/chat")
def chatbot(request: ChatRequest):
    """Endpoint to interact with the city chatbot."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    response = chat_with_gpt(request.messages, request.city)
    return {"response": response}
