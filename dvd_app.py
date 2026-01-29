from flask import Flask, render_template, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from dotenv import load_dotenv, find_dotenv
import os 
from pathlib import Path

"""
Overall updates to make:
5. Make it accessible anywhere
Home Page: 
3. Show Titles that have blanks or nulls in their values
4. Add rotating posters from tmdb
7. Add Hero video to banner
Add Data Page: 
1. TBD Add data
Search Page: 
1. Order by title in search query 
Location Label Page:
1. Add a QR Code page. So when I scan the location labels I will see what all is in that location
2. Add the scanned value into the page
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
    # print(f"DEBUG: {db.metadata.tables.keys()}")

# Access a specific reflected table
## This section below tells the different tables in the database as individual classes.
class Titles(db.Model):
    __table__ = db.metadata.tables[f'{schema}.media_titles']

class Dvds(db.Model):
    __table__ = db.metadata.tables[f'{schema}.dvd_items']

class Purchases(db.Model):
    __table__ = db.metadata.tables[f'{schema}.purchase_info']

# A helper function to get the base "joined" query
def get_base_query():
    return f"""
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
		di.file_size,
        coalesce(di.tmdb_id,mt.tmdb_id) as tmdb_id
    from {schema}.media_titles mt 
    join {schema}.dvd_items di on di.media_title_id  = mt.id
    left join {schema}.purchase_info pi on di.id = pi.dvd_item_id
        """

# -- Creating the home page -- #

@app.route('/')
    ##This method uses full sql to get the data
def home():

    # This is the sql for the most reent dvds added
    sql = get_base_query() + "where pi.purchase_date <> '9999-12-31' and pi.purchase_date is not null order by pi.purchase_date desc limit 10"
    # execute() returns a Result object
    results = db.session.execute(text(sql))
    dvd_data = results.mappings().all()
    # print(f"DEBUG: found {len(dvd_data)}")
    # print(f"DEBUG: First row keys: {dvd_data[0].keys() if results else 'NO DATA'}")
    
    # -- 1. Stats Section -- #
    # --- Counts ---##
    sql2 = get_base_query()
    final_sql = f""" select count(*) 
                    from ({sql2}) as sub 
                    where 1=1 
                    """
    count_results = db.session.execute(text(final_sql)).mappings().all()

    # --- types of Media --- #
    sql2 = get_base_query()
    final_sql = f""" select type, count(type) 
                    from ({sql2}) as sub 
                    where 1=1 
                    group by type
                    """
    type_results = db.session.execute(text(final_sql)).mappings().all()

    # --- types of Genres --- #
    sql2 = get_base_query()
    final_sql = f""" select genre, count(genre) 
                    from ({sql2}) as sub 
                    where 1=1 
                    group by genre
                    """
    genre_results = db.session.execute(text(final_sql)).mappings().all()

    # --- total Cost --- #
    sql2 = get_base_query()
    final_sql = f""" select sum(cost), type 
                    from ({sql2}) as sub 
                    where 1=1 
                    group by type
                    """
    cost_results = db.session.execute(text(final_sql)).mappings().all()
    
    # ---- Cost by Disk Type ---- #
    sql2 = get_base_query()
    final_sql = f""" select sum(cost), disk_type 
                    from ({sql2}) as sub 
                    where 1=1 
                    group by disk_type
                    """
    cost_disk_results = db.session.execute(text(final_sql)).mappings().all()

    # ---- Cost by Store ---- #
    sql =  f""" select 	sum (cost) , store 
                from {schema}.purchase_info pi 
                group by store
                order by store;
                    """
    cost_store_results = db.session.execute(text(sql)).mappings().all()

    # print(f"DEBUG: SQL: {sql}")
    # print(f"DEBUG: First row keys: {dvd_data[0].keys() if cost_store_results else 'NO DATA'}")

    return render_template('home.html', dvds=dvd_data, 
                           counts=count_results, 
                           types=type_results, 
                           genres=genre_results,
                           costs=cost_results,
                           cost_disks=cost_disk_results,
                           cost_stores=cost_store_results
                           )

# -- Creating the Search Page -- #

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

# -- Created the QR Code Results Page -- #
@app.route('/qr')
def qr():
    # Capture multiple search inputs from the URL/Form
    location_query = request.args.get('location', '')

    # Start with base query, make it a subquery to make filtering easier
    base_sql = get_base_query() 
    
    # dynamic case insinsitive search
    final_sql = f"SELECT * FROM ({base_sql}) as sub WHERE 1=1"
    params = {}
        
    if location_query:
        final_sql += " AND location_label ILIKE :loc"
        params['loc'] = f"%{location_query}%"

    # 4. Execute and get results
    results = db.session.execute(text(final_sql), params).mappings().all()

    count_sql = f"select count(*) from ({base_sql} where location_label ILIKE :loc)"
    count_results = db.session.execute(text(count_sql),params).mappings().all()
    
    return render_template('qr_code.html', box_results=results, counts=count_results, param=params)

@app.route('/add_media', methods=['GET', 'POST'])
def add_media():
    new_id = None
    if request.method == 'POST':
        
        # Check if the "Media Form" was submitted
        if 'submit_media' in request.form:
            new_id = None

            is_ongoing = request.form.get('ongoing_ind')=='on'
            is_complete = request.form.get('complete_collection')=='on'

            new_media = Titles(
                title = request.form.get('title'),
                type = request.form.get('type'),
                genre = request.form.get('genre'),
                total_seasons = request.form.get('total_seasons'),
                ongoing_ind = is_ongoing,
                complete_collection = is_complete,
                brand = request.form.get('brand'),
                tmdb_id = request.form.get('tmdb_id')
            )
            db.session.add(new_media)
            db.session.commit()

            new_id = new_media.id

        # Check if the "DVD Form" was submitted
        elif 'submit_dvd' in request.form:
            new_id = None
            new_dvd = Dvds(
                season_number = request.form.get('season_number'),
                season_part = request.form.get('season_part'),
                episodes = request.form.get('episodes'),
                location = request.form.get('location'),
                season_name = request.form.get('season_name'),
                box_set = request.form.get('box_set'),
                complete_season = request.form.get('complete_season'),
                tmdb_id_dvd = request.form.get('tmdb_id_dvd'),
                disk_type = request.form.get('disk_type'),
                disk_region = request.form.get('disk_region'),
                file_size = request.form.get('file_size'),
                category = request.form.get('category'),
                compressed = request.form.get('compressed'),
                adjusted_file_size = request.form.get('adjusted_file_size'),
                disk_type_uploaded = request.form.get('disk_type_uploaded')
            )
            db.session.add(new_dvd)
            db.session.commit()

            new_id = new_dvd.id

        # Check if the "Purchase Form" was submitted
        elif 'submit_purchase' in request.form:
            new_id = None
            new_purchase = Purchases(
                purchase_date = request.form.get('purchase_date'),
                cost = request.form.get('cost'),
                store = request.form.get('store'),
                condition = request.form.get('condition'),
                notes = request.form.get('notes'),
            )
            db.session.add(new_purchase)
            db.session.commit()

            new_id = new_purchase.id

    # Re-render the same page with the new ID available to show the next section
    return render_template('add_media.html', movie_id=new_id)



if __name__ == '__main__':
    app.run(debug=True)