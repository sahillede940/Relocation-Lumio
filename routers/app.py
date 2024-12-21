import openai
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.future import select
from sqlalchemy import or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from Models.models import CityMetrics
from utils.query_data import query_rag
from utils.city_score import get_city_score
from utils.fetch_news import fetch_news
from utils.City_Data.get_city_data import get_city_data
from Database.get_news_db import get_news_db, News
from Database.get_verified_db import get_verified_db
from Database.get_city_list_db import get_city_list_db, CityMetricsQuery
from utils.constants import MAIN_URL
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Create the router
api_router = APIRouter()


@api_router.get("/get-cities-list")
async def get_items_list(
    q: Optional[str] = Query(
        None, description="City name and state name to search"
    ),
    db: Session = Depends(get_city_list_db),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Search term is required.")

    search_query = f"%{q.strip()}%"

    query = db.query(CityMetricsQuery).filter(
        or_(
            CityMetricsQuery.city.ilike(search_query),
            CityMetricsQuery.state_name.ilike(search_query),
            CityMetricsQuery.state_code.ilike(search_query)
        )
    ).order_by(
        case(
            (CityMetricsQuery.city.ilike(search_query), 1),
            else_=2
        )
    ).limit(20)

    cities = query.all()

    if not cities:
        return {
            "results": [],
            "success": False,
            "message": "No matching cities found.",
        }

    return {
        "results": [
            {
                "id": city.id,
                "city": city.city,
                "state_name": city.state_name,
                "state_code": city.state_code,
                "value": f"{city.city}, {city.state_code}",
            }
            for city in cities
        ],
        "success": True,
    }


# Pydantic models for request validation
class CityRequest(BaseModel):
    id: int
    city: Optional[str] = None
    state_code: Optional[str] = None
    state_name: Optional[str] = None


class QueryRequest(BaseModel):
    from_city: Optional[CityRequest] = None
    to_city: Optional[CityRequest] = None


@api_router.post("/comparison")
async def handle_query(request: QueryRequest, db: Session = Depends(get_verified_db)):
    """
    Compare metrics between two cities.
    """

    def model_to_dict(instance):
        return {c.name: getattr(instance, c.name) for c in instance.__table__.columns}

    # Validate input
    if not request.from_city or not request.to_city:
        raise HTTPException(
            status_code=400, detail="Both from_city and to_city are required."
        )

    # Fetch result from RAG function
    result = query_rag(request.from_city.city, request.to_city.city)
    result["heading"] = {
        "title": "BIG MOVE!",
        "description": f"A move from {request.from_city.city} to {request.to_city.city} covers a significant distance. This move would bring substantial changes in cost of living, climate, and urban environment.",
    }

    city_1_data = get_city_data(request.from_city, db)
    city_2_data = get_city_data(request.to_city, db)
    db.commit()
    db.refresh(city_1_data)
    db.refresh(city_2_data)

    city_1_data = model_to_dict(city_1_data)
    city_2_data = model_to_dict(city_2_data)
    # Check if city data exists
    if not city_1_data or not city_2_data:
        raise HTTPException(
            status_code=404, detail="City data not found for one or both cities."
        )

    return {
        **result,
        "city_1": city_1_data,
        "city_2": city_2_data,
        "comparison": get_city_score(city_2_data),
        "success": True,
    }


@api_router.get("/similar_posts")
async def get_similar_posts(
    city: Optional[str] = Query(
        None, description="Search term to find similar posts"
    ),
    db: AsyncSession = Depends(get_news_db),
):
    results = db.execute(select(News).filter(
        News.name.ilike(f"%{city}%"))).scalars().all()[0]

    def serialize_news(news):
        return {
            "id": news.id,
            "name": news.name,
            "url": news.url,  # Add other attributes as needed
        }

    results = serialize_news(results)
    results = fetch_news(results["url"])

    return {
        "results": results,
        "success": True,
    }


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    city: Optional[str] = None


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


# Define your request model
class ContactUsRequest(BaseModel):
    name: str
    email: str
    phone: str
    comments: str


api_router = APIRouter()


@api_router.post("/contact-us")
def contact_us(request: ContactUsRequest):
    # Replace MAIN_URL with the actual base URL
    URL = f"{MAIN_URL}/contact-gay-real-estate.html"

    try:
        # Set up Selenium for headless operation
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        # Ensure the WebDriver is correctly installed and in PATH
        driver = webdriver.Chrome(options=options)

        # Navigate to the page
        driver.get(URL)

        # Fill the form fields
        try:
            # Locate and fill the input fields
            driver.find_element(By.ID, "clientName").send_keys(request.name)
            driver.find_element(By.ID, "clientEmail").send_keys(request.email)
            driver.find_element(By.ID, "clientPhone").send_keys(request.phone)
            driver.find_element(By.ID, "clientComments").send_keys(
                request.comments)
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error filling form: {str(e)}")

        # Check and click the "Send" button
        try:
            submit_button = driver.find_element(By.ID, "contactUsSubmit")
            ActionChains(driver).move_to_element(
                submit_button).click().perform()
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Error clicking submit button: {str(e)}")

        # Dynamically wait for the new page to load
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "successMsg"))
            )
            success_msg = "Thank You! We have received your request and one of our staff members will reply shortly."
            return {"success": True, "message": success_msg}
        except Exception as e:
            raise HTTPException(
                status_code=500, detail="Success message not found after submission.")

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"An error occurred: {str(e)}")
    finally:
        driver.quit()
