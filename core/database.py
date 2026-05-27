from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Float, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class Company(Base):
    __tablename__ = 'companies'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    legal_name = Column(String(255))
    registration_number = Column(String(100), unique=True)

    # Location
    address = Column(Text)
    city = Column(String(100))
    area = Column(String(100))
    latitude = Column(Float)
    longitude = Column(Float)

    # Business Info
    sector = Column(String(255))
    field = Column(String(255))
    description = Column(Text)

    # Contact
    phone = Column(String(50))
    email = Column(String(255))
    website = Column(String(255))

    # Social / External
    linkedin_url = Column(String(255))
    facebook_url = Column(String(255))
    instagram_url = Column(String(255))
    twitter_url = Column(String(255))
    google_maps_url = Column(String(255))
    rating = Column(Float)
    review_count = Column(Integer)

    # Firmographic
    employee_count = Column(String(50))
    founded_year = Column(String(20))

    # Enrichment tracking
    website_enriched = Column(Boolean, default=False)
    website_enriched_at = Column(DateTime(timezone=True))

    # Raw source payloads
    source_data = Column(JSON)
    last_scraped_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Company(name='{self.name}', city='{self.city}')>"


def run_migrations(engine):
    """Add new columns to existing SQLite databases without dropping data."""
    new_columns = [
        ("facebook_url",        "VARCHAR(255)"),
        ("instagram_url",       "VARCHAR(255)"),
        ("twitter_url",         "VARCHAR(255)"),
        ("founded_year",        "VARCHAR(20)"),
        ("website_enriched",    "BOOLEAN DEFAULT 0"),
        ("website_enriched_at", "DATETIME"),
    ]
    with engine.connect() as conn:
        for col_name, col_type in new_columns:
            try:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE companies ADD COLUMN {col_name} {col_type}"
                    )
                )
                conn.commit()
            except Exception:
                pass  # column already exists — fine
