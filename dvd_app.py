from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from dotenv import load_dotenv, find_dotenv
import os 
from pathlib import Path

"""
Overall updates to make:
2. add a footer
3. add a header or hamberger menu
4. Make it pretty
5. Make it accessible anywhere
Home Page: 
1. Add a Count of Movies and Tv Shows
2. Add the search bar to the main page 
3. Show Titles that have blanks or nulls in their values
4. Add rotating posters from tmdb
Location Label Page:
1. Add a QR Code page. So when I scan the location labels I will see what all is in that location
"""

dotenv_path = Path('.') / 'config' / '.env'

load_dotenv(dotenv_path)

app = Flask(__name__)

user = os.getenv('DB_USER')
password = os.getenv('DB_PASS')
host = os.getenv('DB_HOST')
dbname = os.getenv('DB_NAME')
schema = os.getenv('DB_SCHEMA')

app.config['SQLALCHEMY_DATABASE_URI']=f'postgresql://{user}:{password}@{host}/{dbname}'

db=SQLAlchemy(app)
with app.app_context():
    # Loads all table structures into db.metadata
    db.metadata.reflect(bind=db.engine,schema=schema)
    print(db.metadata.tables.keys())

# Access a specific reflected table
class Titles(db.Model):
    __table__ = db.metadata.tables[f'{schema}.media_titles']

class Dvds(db.Model):
    __table__ = db.metadata.tables[f'{schema}.dvd_items']

class Purchases(db.Model):
    __table__ = db.metadata.tables[f'{schema}.purchase_info']

# A helper function to get the base "joined" query
def get_base_query():
    return """
   select 	mt.id as media_title_id,  
		di.media_title_id as dvd_med_id,
		di.id as dvd_id,
		pi.dvd_item_id  as pi_dvd_id,
		pi.id as pi_id,
		mt."type",
		mt.genre,
		mt.title,
		di.season_name,
		di.season_number,
		di.season_part,
        di.location_label,
		pi.purchase_date,
		pi."cost",
		pi.store,
		pi."condition",
		pi.notes,
		di.box_set,
		di.complete_season,
		di.category,
		mt.complete_collection,
        di.disk_type,
		di.file_size
    from media_catalog.media_titles mt 
    join media_catalog.dvd_items di on di.media_title_id  = mt.id
    left join media_catalog.purchase_info pi on di.id = pi.dvd_item_id
        """

@app.route('/')
    ##This method uses full sql to get the data
def index():

    # Use full SQL with schema prefixes for your 3-table join
    sql = get_base_query() + "where pi.purchase_date <> '9999-12-31' and pi.purchase_date is not null order by pi.purchase_date desc limit 10"
    # execute() returns a Result object
    results = db.session.execute(text(sql))
    
    dvd_data = results.mappings().all()
    # print(f"DEBUG: found {len(dvd_data)}")
    # print(f"DEBUG: First row keys: {dvd_data[0].keys() if results else 'NO DATA'}")
    
    return render_template('index.html', dvds=dvd_data)

@app.route('/search')
def search():
    # Capture multiple search inputs from the URL/Form
    name_query = request.args.get('name', '')
    location_query = request.args.get('location', '')

    # Start with base query, make it a subquery to make filtering easier
    base_sql = get_base_query() 
    
    # dynamic case insinsitive search
    final_sql = f"SELECT * FROM ({base_sql}) as sub WHERE 1=1"
    params = {}

    if name_query:
        final_sql += " AND title ILIKE :name or season_name ILIKE :name"
        params['name'] = f"%{name_query}%"
        
    if location_query:
        # Assuming 'location_label' is a column in your joined tables
        final_sql += " AND location_label ILIKE :loc"
        params['loc'] = f"%{location_query}%"

    # 4. Execute and get results
    results = db.session.execute(text(final_sql), params).mappings().all()
    
    return render_template('search.html', search_dvds=results)

if __name__ == '__main__':
    app.run(debug=True)