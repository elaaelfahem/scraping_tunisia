import Levenshtein
from sqlalchemy.orm import Session
from core.database import Company
from core.filters import sanitize_company_data
import json

class DataIntegrator:
    def __init__(self, db_session: Session):
        self.db = db_session

    def find_best_match(self, name: str, city: str = None, threshold: float = 0.85):
        """Finds existing company in DB using fuzzy matching on name."""
        # Simple implementation: fetch companies in the same city and compare names
        query = self.db.query(Company)
        if city:
            query = query.filter(Company.city == city)
        
        candidates = query.all()
        best_match = None
        highest_score = 0
        
        for candidate in candidates:
            score = Levenshtein.ratio(name.lower(), candidate.name.lower())
            if score > highest_score:
                highest_score = score
                best_match = candidate
        
        if highest_score >= threshold:
            return best_match, highest_score
        return None, 0

    def add_or_update_company(self, company_data: dict) -> Company:
        """Adds a new company or updates an existing one with new info."""
        # Sanitize all fields first (removes placeholders like 'xxxxx', etc.)
        company_data = sanitize_company_data(company_data)

        name = company_data.get('name')
        city = company_data.get('city')

        # Separate source_data so it doesn't interfere with column assignment
        source_payload = company_data.pop('source_data', None)

        existing_company, score = self.find_best_match(name, city)

        if existing_company:
            print(f"Updating existing company: {existing_company.name} (Match score: {score:.2f})")
            # Update fields if they are not set or we have "better" data
            for key, value in company_data.items():
                if not hasattr(existing_company, key) or not value:
                    continue

                current_val = getattr(existing_company, key)

                should_update = False
                # 1. Current value is empty / None / blank string
                if not current_val or (isinstance(current_val, str) and not current_val.strip()):
                    should_update = True
                # 2. Current value is a stub URL
                elif isinstance(current_val, str) and current_val.strip().lower() in [
                    "www.", "http://www.", "https://www.", "none", "n/a",
                ]:
                    should_update = True
                # 3. New value is longer / more complete for string fields
                elif isinstance(value, str) and isinstance(current_val, str):
                    if key in ('address', 'email', 'phone', 'website', 'field', 'sector', 'description'):
                        if len(value.strip()) > len(current_val.strip()):
                            should_update = True
                    if key.endswith('_url') and len(value) > len(current_val):
                        should_update = True

                if should_update:
                    setattr(existing_company, key, value)

            # Merge source data
            if source_payload:
                current_source = existing_company.source_data or {}
                current_source.update(source_payload)
                existing_company.source_data = current_source

            self.db.commit()
            return existing_company
        else:
            print(f"Creating new company record: {name}")
            # Filter to only valid Company column names to avoid SQLAlchemy errors
            valid_keys = {c.name for c in Company.__table__.columns}
            clean_data = {k: v for k, v in company_data.items() if k in valid_keys}
            if source_payload:
                clean_data['source_data'] = source_payload

            new_company = Company(**clean_data)
            self.db.add(new_company)
            self.db.commit()
            return new_company

# Example usage (would be called by n8n or a main script)
if __name__ == "__main__":
    # This would need a live DB session
    pass
