from sqlalchemy import Column, String, Index, DateTime, Integer
from . import Base
from datetime import datetime


class CityMetrics(Base):
    __tablename__ = "city_metrics"

    id = Column(Integer, primary_key=True, index=True)
    search_id = Column(Integer, index=True)
    
    city = Column(String, index=True)
    state_code = Column(String)
    state_name = Column(String, index=True)
    
    home_price = Column(String)
    property_tax = Column(String)
    home_appreciation_rate = Column(String)
    price_per_square_foot = Column(String)
    education = Column(String)
    healthcare_fitness = Column(String)
    weather_grade = Column(String)
    air_quality_index = Column(String)
    commute_transit_score = Column(String)
    accessibility = Column(String)
    culture_entertainment = Column(String)
    unemployment_rate = Column(String)
    recent_job_growth = Column(String)
    future_job_growth_index = Column(String)
    median_household_income = Column(String)
    state_income_tax = Column(String)
    utilities = Column(String)
    food_groceries = Column(String)
    sales_tax = Column(String)
    transportation_cost = Column(String)

    # dates
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # Define composite index for optimized search
    __table_args__ = (
        Index("idx_city_state", "city", "state_name"),
    )
