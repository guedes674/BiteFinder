import mysql.connector
import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS
import bcrypt
import jwt
import datetime
import random
import string
import sys
import json
from flask_socketio import SocketIO, join_room, leave_room, emit

sys.path.insert(0,"src/vectorization/")
import vectorization as vect

# Load environment variables
load_dotenv()

def get_db_connection():
    """Establish connection to SingleStore database"""
    conn = mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USERNAME"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_DATABASE"),
        port=int(os.getenv("DB_PORT"))
    )
    return conn

#drop all tables
def drop_all_tables():
    """Drop all tables in the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DROP TABLE IF EXISTS user_preference")
        cursor.execute("DROP TABLE IF EXISTS user_restaurant")
        cursor.execute("DROP TABLE IF EXISTS restaurant_image")
        cursor.execute("DROP TABLE IF EXISTS group_user")
        cursor.execute("DROP TABLE IF EXISTS `group`")
        cursor.execute("DROP TABLE IF EXISTS restaurant")
        cursor.execute("DROP TABLE IF EXISTS user")
        cursor.execute("DROP TABLE IF EXISTS photo")
        
        conn.commit()
        print("All tables dropped successfully")
        
    except Exception as e:
        print(f"Error dropping tables: {e}")
        conn.rollback()
        
    finally:
        cursor.close()
        conn.close()
# Uncomment the line below to drop all tables before initializing
#drop_all_tables()

def init_db():
    """Initialize database tables if they don't exist"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Create user table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user (
            username VARCHAR(100) PRIMARY KEY,
            name VARCHAR(80) NOT NULL,
            password VARCHAR(100) NOT NULL,
            email VARCHAR(100) NOT NULL,
            food_vector VECTOR(4096),
            place_vector VECTOR(4096),
            history_food_vector VECTOR(4096),
            history_place_vector VECTOR(4096),
            history INT 
        )
        ''')
        
        # Create restaurant table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS restaurant (
            restaurant_id VARCHAR(100) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            rating FLOAT NOT NULL,
            url_location VARCHAR(255) NOT NULL,
            food_vector VECTOR(4096),
            place_vector VECTOR(4096),
            price_range_max INT NOT NULL,
            price_range_min INT NOT NULL,
            price_level INT NOT NULL,
            type VARCHAR(100) NOT NULL,
            reservable BOOLEAN NOT NULL,
            vegetarian BOOLEAN NOT NULL,
            summary VARCHAR(500) NOT NULL
        )
        ''')

        # Create Scheduale table 
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduale (
            id INT AUTO_INCREMENT PRIMARY KEY,
            end VARCHAR(20) NOT NULL,
            start VARCHAR(20) NOT NULL,
            day VARCHAR(10) NOT NULL,
            restaurant_id VARCHAR(100) NOT NULL
        )
        ''')

        # Create photo table 
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS photo (
            url VARCHAR(500) PRIMARY KEY,
            restaurant_id VARCHAR(100) NOT NULL
        )
        ''')
        
        # Create group table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS `group` (
            code VARCHAR(10) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            status ENUM('active', 'inactive') NOT NULL,
            creator_username VARCHAR(100) NOT NULL,
            max_members INT DEFAULT 6,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            food_vector VECTOR(4096),
            place_vector VECTOR(4096)
        )
        ''')
        
        # Create group_user table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_user (
            group_code VARCHAR(10),
            username VARCHAR(100),
            is_ready BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (group_code, username)
        )
        ''')
        
        # Create user_restaurant table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_restaurant (
            username VARCHAR(100),
            restaurant_id VARCHAR(100),
            PRIMARY KEY (username, restaurant_id)
        )
        ''')
        
        # Create user_preference table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_preference (
            username VARCHAR(100),
            preference VARCHAR(100),
            PRIMARY KEY (username,preference)
        )
        ''')

        # Creat user history

        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_history (
            username VARCHAR(100) NOT NULL,
            restaurant_id VARCHAR(100) NOT NULL,
            id INT AUTO_INCREMENT PRIMARY KEY
        )
        ''')
        
        conn.commit()
        print("Database tables created successfully")
        
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
        
    finally:
        cursor.close()
        conn.close()

# Add this right after defining the app
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize database tables
init_db()

# JWT configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")  # Change in production
JWT_EXPIRATION_DAYS = 7


# Add WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('join_group')
def handle_join_group(data):
    room = data['group_code']
    join_room(room)
    print(f'Client joined room: {room}')

@socketio.on('leave_group')
def handle_leave_group(data):
    room = data['group_code']
    leave_room(room)
    print(f'Client left room: {room}')

# Add this event handler near the other socketio event handlers
# Update the group_dissolved_by_host handler
@socketio.on('group_dissolved_by_host')
def handle_group_dissolved(data):
    room = data.get('group_code')
    if room:
        print(f"Received group_dissolved_by_host for room {room}")
        
        # Mark the group as inactive in the database
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE `group` SET status = 'inactive' WHERE code = %s",
                (room,)
            )
            conn.commit()
            print(f"Group {room} marked as inactive in database")
        except Exception as e:
            print(f"Error updating group status: {e}")
        finally:
            cursor.close()
            conn.close()
        
        # Forward the dissolution event to all clients in the room
        emit('group_dissolved', {
            'message': data.get('message', 'The host has dissolved the group'),
            'redirect': True
        }, room=room)
        
        print(f"Group dissolution event sent to room {room}")

@socketio.on('member_leaving')
def handle_member_leaving(data):
    room = data.get('group_code')
    username = data.get('username')
    name = data.get('name', username)
    
    if room and username:
        print(f"Member {username} is leaving room {room}")
        # Enviar para todos os outros membros do grupo
        emit('member_left', {
            'username': username,
            'name': name,
            'message': f"{name} has left the group"
        }, room=room)

# Helper functions
def hash_password(password):
    """Hash a password for storage"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(stored_password, provided_password):
    """Verify a stored password against one provided by user"""
    return bcrypt.checkpw(provided_password.encode('utf-8'), stored_password.encode('utf-8'))

def generate_token(username):
    """Generate a JWT token"""
    payload = {
        'exp': datetime.datetime.utcnow() + datetime.timedelta(days=JWT_EXPIRATION_DAYS),
        'iat': datetime.datetime.utcnow(),
        'sub': username
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def generate_group_code():
    """Generate a unique 6-character group code"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# USER AUTHENTICATION ENDPOINTS
@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    
    # Basic validation
    if not all(k in data for k in ('username', 'name', 'email', 'password','place_preferences','food_preferences')):
        print(data)
        return jsonify({'error': 'Missing required fields'}), 400
    
    username = data['username']
    name = data['name']
    email = data['email']
    password = data['password']
    food_preferences = data['food_preferences']
    place_preferences = data['place_preferences']

    food_embbeding = vect.create_embeddings_from_preferences(food_preferences,1)
    place_embbeding = vect.create_embeddings_from_preferences(place_preferences)

    # Hash the password
    hashed_password = hash_password(password)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if user already exists
        cursor.execute("SELECT username FROM user WHERE username = %s OR email = %s", (username, email))
        if cursor.fetchone():
            return jsonify({'error': 'Username or email already registered'}), 409
        
        # Insert new user
        cursor.execute(
            "INSERT INTO user (username, name, password, email, food_vector, place_vector, history) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (username, name, hashed_password, email, json.dumps(food_embbeding), json.dumps(place_embbeding),0)
        )
    
        for pref in food_preferences:
            cursor.execute("INSERT INTO user_preference (username, preference) VALUES (%s, %s)",
                (username, pref)
            )
        for pref in place_preferences:
            cursor.execute("INSERT INTO user_preference (username, preference) VALUES (%s, %s)",
                (username, pref)
        )

        conn.commit()
        
        return jsonify({'message': 'User registered successfully'}), 201
    
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    
    # Allow login with username or email
    if not (('username' in data or 'email' in data) and 'password' in data):
        return jsonify({'error': 'Missing login credentials'}), 400
    
    password = data['password']
    login_field = 'username' if 'username' in data else 'email'
    login_value = data[login_field]

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get user by username or email
        query = f"SELECT username, name, email, password FROM user WHERE {login_field} = %s"
        cursor.execute(query, (login_value,))
        user = cursor.fetchone()
        
        if not user or not verify_password(user['password'], password):
            return jsonify({'error': 'Invalid credentials'}), 401

        cursor.execute(
            "SELECT preference FROM user_preference WHERE username = %s",
            (user['username'],)
        )
        preferences = [row['preference'] for row in cursor.fetchall()]

        # Generate token
        token = generate_token(user['username'])
        
        return jsonify({
            'token': token,
            'user': {
                'username': user['username'],
                'name': user['name'],
                'email': user['email'],
                'preferences': preferences
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# GROUP MANAGEMENT ENDPOINTS
@app.route('/groups/create', methods=['POST'])
def create_group():
    data = request.get_json()
    
    if not all(k in data for k in ('name', 'username')):
        return jsonify({'error': 'Missing required fields'}), 400
    
    name = data['name']
    username = data['username']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Validate that user exists
        cursor.execute("SELECT username FROM user WHERE username = %s", (username,))
        if not cursor.fetchone():
            return jsonify({'error': 'User not found'}), 404
        
        # Generate a unique group code (ensure it doesn't already exist)
        code = generate_group_code()
        cursor.execute("SELECT code FROM `group` WHERE code = %s", (code,))
        while cursor.fetchone():
            code = generate_group_code()
            cursor.execute("SELECT code FROM `group` WHERE code = %s", (code,))
        
        # Create the group
        cursor.execute(
            "INSERT INTO `group` (code, name, status, creator_username) VALUES (%s, %s, 'active', %s)",
            (code, name, username)
        )
        

        # Quando adicionar o criador ao grupo, marcá-lo como pronto por padrão
        cursor.execute(
            "INSERT INTO group_user (group_code, username, is_ready) VALUES (%s, %s, TRUE)",
            (code, username)
        )
        
        conn.commit()
        
        return jsonify({
            'message': 'Group created successfully',
            'code': code,
            'name': name

        }), 201
    
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# Update the join_group route
@app.route('/groups/join', methods=['POST'])
def join_group():
    data = request.get_json()
    
    if not all(k in data for k in ('code', 'username')):
        return jsonify({'error': 'Missing required fields'}), 400
    
    code = data['code']
    username = data['username']
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Validate that user exists
        cursor.execute("SELECT name FROM user WHERE username = %s", (username,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Check if the group exists and is active
        cursor.execute("SELECT * FROM `group` WHERE code = %s AND status = 'active'", (code,))
        group = cursor.fetchone()
        
        if not group:
            return jsonify({'error': 'Group not found or inactive'}), 404
        
        # Check if user is already in the group
        cursor.execute("SELECT * FROM group_user WHERE group_code = %s AND username = %s", (code, username))
        if cursor.fetchone():
            return jsonify({'error': 'User already in this group'}), 409
        
        # Add user to the group
        cursor.execute(
            "INSERT INTO group_user (group_code, username) VALUES (%s, %s)",
            (code, username)
        )
        
        # Notify others via WebSocket that user joined
        user_name = user['name']
        socketio.emit('user_joined', {
            'username': username,
            'name': user_name,
            'message': f"{user_name} has joined the group"
        }, room=code)
        
        # Get updated member list
        cursor.execute("""
            SELECT u.username, u.name, gu.is_ready, 
                (u.username = g.creator_username) as is_host
            FROM user u
            JOIN group_user gu ON u.username = gu.username
            JOIN `group` g ON gu.group_code = g.code
            WHERE gu.group_code = %s
        """, (code,))
        
        # Format members consistently
        members = []
        for row in cursor.fetchall():
            members.append({
                'username': row['username'],
                'name': row['name'],
                'is_ready': bool(row['is_ready']),
                'is_host': bool(row['is_host'])
            })
        
        # Emit updated member list
        socketio.emit('members_update', {'members': members}, room=code)
        
        conn.commit()
        
        return jsonify({
            'message': 'Joined group successfully',
            'group': {
                'code': group['code'],
                'name': group['name']
            }
        }), 200
    
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# Endpoint to get user info and preferences
@app.route('/user/<username>', methods=['GET'])
def get_user(username):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Get user info
        cursor.execute("SELECT username, name, email FROM user WHERE username = %s", (username,))
        user = cursor.fetchone()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get user preferences
        cursor.execute(
            "SELECT preference FROM user_preference WHERE username = %s",
            (username,)
        )
        preferences = [row['preference'] for row in cursor.fetchall()]
        user['preferences'] = preferences
        
        return jsonify({'user': user}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

@app.route('/groups/user/<username>', methods=['GET'])
def get_user_groups(username):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Validate that user exists
        cursor.execute("SELECT username FROM user WHERE username = %s", (username,))
        if not cursor.fetchone():
            return jsonify({'error': 'User not found'}), 404
            
        cursor.execute("""
            SELECT g.code, g.name, g.status, g.created_at
            FROM `group` g
            JOIN group_user gu ON g.code = gu.group_code
            WHERE gu.username = %s AND g.status = 'active'
        """, (username,))
        
        groups = cursor.fetchall()
        
        return jsonify({'groups': groups}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# RESTAURANT ENDPOINTS
@app.route('/restaurants', methods=['GET'])
def get_restaurants():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT * FROM restaurant")
        restaurants = cursor.fetchall()
        
        # Get images for each restaurant
        for restaurant in restaurants:
            restaurant_id = restaurant['restaurant_id']  # Changed from 'id' to 'restaurant_id'
            cursor.execute("SELECT image_url FROM restaurant_image WHERE restaurant_id = %s", (restaurant_id,))
            images = cursor.fetchall()
            restaurant['images'] = [img['image_url'] for img in images]
            restaurant['rating'] = float(restaurant['rating'])  # Convert Decimal to float for JSON
        
        return jsonify({'restaurants': restaurants}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()


# RESTAURANT FOR USER ENDPOINTS
@app.route('/restaurants/<username>', methods=['GET'])
def get_restaurants_preference(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT history_food_vector, history_place_vector FROM user WHERE username = %s AND history > 0",(username,))

        response = cursor.fetchall()
        if len(response) != 0 :
            history_food_vector, history_place_vector = cursor.fetchall()[0]
            history_food_vector = json.loads(history_food_vector)
            history_place_vector = json.loads(history_place_vector)
        
        cursor.execute("SELECT food_vector, place_vector FROM user WHERE username = %s",(username,))
        food_vector, place_vector = cursor.fetchall()[0]
        place_vector = json.loads(place_vector)
        
        if len(response) != 0:
            place_vector = vect.average_embedding([history_place_vector,place_vector])

        print(type(place_vector))
        print(place_vector)

        cursor1 = conn.cursor(dictionary=True)

        cursor1.execute("Set @query_vec = (%s):> VECTOR(4096)",(json.dumps(place_vector),))

        cursor1.execute("SELECT *, place_vector <*> @query_vec AS score FROM restaurant ORDER BY score DESC LIMIT 5")

        restaurants = cursor.fetchall()
        print(food_vector)
        food_vector = json.loads(food_vector)

        if len(response) != 0:
            food_vector = vect.average_embedding([history_food_vector,food_vector])
        cursor1.execute("Set @query_vec = (%s):> VECTOR(4096)",(json.dumps(food_vector),))

        print("1234")

        cursor1.execute("SELECT *, food_vector <*> @query_vec AS score FROM restaurant ORDER BY score DESC LIMIT 5")


        print("123213123")
        restaurants = restaurants + cursor1.fetchall()
        restaurants_no_doubles = []
        for item in restaurants:
            if restaurants.count(item) > 1 and item not in restaurants_no_doubles:
                restaurants_no_doubles.append(item)

        print("123323")
        # Get images for each restaurant
        out_restaurants = []
        for restaurant in restaurants:
            print(len(restaurant))
            restaurant_id, restaurant_name,rating, url,_,_,price_range_max,price_range_min,price_level,_,_,_,summary,_ = restaurant

            print(restaurant_id)
            cursor1.execute("SELECT url FROM photo WHERE restaurant_id = %s LIMIT 1", (restaurant_id,))
            print("HOLLLAAA")
            images = cursor1.fetchall()
            if price_range_min == 0:
                out_restaurant = {
                'restaurant_name': restaurant_name,
                'rating': rating,
                'url':url,
                'price_level':price_level,
                'summary':summary,
                'images': [img['url'] for img in images],
                'price_range': "" 

            }
            else :
                out_restaurant = {
                    'restaurant_name': restaurant_name,
                    'rating': rating,
                    'url':url,
                    'price_level':price_level,
                    'summary':summary,
                    'images': [img['url'] for img in images],
                    'price_range': "(" + str(price_range_min) + "€-" + str(price_range_max) + "€)" 

                }
            print(out_restaurant['restaurant_name'])
            out_restaurants.append(out_restaurant)

        return jsonify({'restaurants': out_restaurants}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor1.close()
        cursor.close()
        conn.close()

@app.route('/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        cursor.execute("SELECT username, name, email FROM user")
        users = cursor.fetchall()
        
        for user in users:
            cursor.execute(
                "SELECT preference FROM user_preference WHERE username = %s",
                (user['username'],)
            )
            preferences = [row['preference'] for row in cursor.fetchall()]
            user['preferences'] = preferences

        return jsonify({'users': users}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# RESTAURANT MANAGEMENT ENDPOINTS
@app.route('/restaurants', methods=['POST'])
def add_restaurant():
    data = request.get_json()
    
    if not all(k in data for k in ('restaurant_id', 'name', 'rating', 'url_location')):
        return jsonify({'error': 'Missing required fields'}), 400
    
    restaurant_id = data['restaurant_id']
    name = data['name']
    rating = data['rating']
    url_location = data['url_location']
    image_urls = data.get('image_urls', [])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Add restaurant
        cursor.execute("""
            INSERT INTO restaurant (restaurant_id, name, rating, url_location)
            VALUES (%s, %s, %s, %s)
        """, (restaurant_id, name, rating, url_location))
        
        # Add images
        for image_url in image_urls:
            cursor.execute("""
                INSERT INTO restaurant_image (restaurant_id, image_url)
                VALUES (%s, %s)
            """, (restaurant_id, image_url))
        
        conn.commit()
        
        return jsonify({
            'message': 'Restaurant added successfully',
            'restaurant_id': restaurant_id,  # Changed from 'id' to 'restaurant_id'
        }), 201
    
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

@app.route('/groups/<code>/members', methods=['GET'])
def get_group_members(code):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if the group exists
        cursor.execute("SELECT * FROM `group` WHERE code = %s", (code,))
        group = cursor.fetchone()
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # Get all members of the group with their ready status
        cursor.execute("""
            SELECT u.username, u.name, gu.is_ready, 
                   (u.username = g.creator_username) as is_host
            FROM user u
            JOIN group_user gu ON u.username = gu.username
            JOIN `group` g ON gu.group_code = g.code
            WHERE gu.group_code = %s
        """, (code,))
        
        members = cursor.fetchall()
        
        return jsonify({'members': members}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# Endpoint para pegar informações do grupo
@app.route('/groups/<code>', methods=['GET'])
def get_group(code):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if the group exists
        cursor.execute("SELECT * FROM `group` WHERE code = %s", (code,))
        group = cursor.fetchone()
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
            
        # Incluir o criador do grupo na resposta
        return jsonify({'group': group}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# Endpoint para marcar-se como pronto ou não pronto
@app.route('/groups/<code>/ready', methods=['POST'])
def update_ready_status(code):
    data = request.get_json()
    
    if not all(k in data for k in ('username', 'is_ready')):
        return jsonify({'error': 'Missing required fields'}), 400
        
    username = data['username']
    is_ready = data['is_ready']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Update ready status
        cursor.execute(
            "UPDATE group_user SET is_ready = %s WHERE group_code = %s AND username = %s",
            (is_ready, code, username)
        )
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'User not found in group'}), 404
            
        conn.commit()
        
        cursor.execute("""
            SELECT u.username, u.name, gu.is_ready, 
                (u.username = g.creator_username) as is_host
            FROM user u
            JOIN group_user gu ON u.username = gu.username
            JOIN `group` g ON gu.group_code = g.code
            WHERE gu.group_code = %s
        """, (code,))
        
        # Ensure consistent format for members data
        members = []
        for row in cursor.fetchall():
            members.append({
                'username': row[0],  # or row['username'] if using dictionary cursor
                'name': row[1],      # or row['name']
                'is_ready': bool(row[2]),  # Convert to boolean
                'is_host': bool(row[3])    # Convert to boolean
            })
        
        # Emit update to all clients in the group room
        socketio.emit('members_update', {'members': members}, room=code)
    
        
        return jsonify({'success': True, 'is_ready': is_ready}), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()
        conn.close()

@app.route('/groups/<code>/leave', methods=['POST'])
def leave_group(code):
    data = request.get_json()
    print(data) 
    
    if 'username' not in data:
        return jsonify({'error': 'Missing username'}), 400
        
    username = data['username']
    is_host = data.get('is_host', False)
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if the group exists
        cursor.execute("SELECT * FROM `group` WHERE code = %s", (code,))
        group = cursor.fetchone()

        print(group)  # Debugging line
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
            
        # Check if user is in the group
        cursor.execute(
            "SELECT * FROM group_user WHERE group_code = %s AND username = %s", 
            (code, username)
        )
        
        # CORREÇÃO: Armazene o resultado em uma variável em vez de usar fetchone() duas vezes
        user_in_group = cursor.fetchone()
        print(user_in_group)  # Debugging line
        
        if not user_in_group:
            return jsonify({'error': 'User not in group'}), 404
            
        # Check if user is the host/creator
        is_creator = (group['creator_username'] == username)
        
        if is_creator or is_host:
            # If the user is the creator, mark the group as inactive
            cursor.execute(
                "UPDATE `group` SET status = 'inactive' WHERE code = %s",
                (code,)
            )

            print("Group status updated to inactive")  # Debugging line
            
            # Notify all clients in the group to redirect to home
            socketio.emit('group_dissolved', {
                'message': 'The host has dissolved the group',
                'redirect': True
            }, room=code)
            print("Group dissolved notification sent")  # Debugging line
            
        else:
            # Get user details for notification
            cursor.execute("SELECT name FROM user WHERE username = %s", (username,))
            user = cursor.fetchone()
            user_name = user.get('name', username) if user else username
            
            # Remove the user from the group
            cursor.execute(
                "DELETE FROM group_user WHERE group_code = %s AND username = %s",
                (code, username)
            )
            
            # Notify other members that someone left
            socketio.emit('member_left', {
                'username': username,
                'name': user_name,
                'message': f"{user_name} has left the group"
            }, room=code)
            
            # Get updated member list
            cursor.execute("""
                SELECT u.username, u.name, gu.is_ready, 
                    (u.username = g.creator_username) as is_host
                FROM user u
                JOIN group_user gu ON u.username = gu.username
                JOIN `group` g ON gu.group_code = g.code
                WHERE gu.group_code = %s
            """, (code,))
            
            # Format members consistently
            members = []
            for row in cursor.fetchall():
                members.append({
                    'username': row['username'],
                    'name': row['name'],
                    'is_ready': bool(row['is_ready']),
                    'is_host': bool(row['is_host'])
                })
            
            # Emit updated member list
            socketio.emit('members_update', {'members': members}, room=code)
            
        conn.commit()
        
        return jsonify({'message': 'Successfully left group'}), 200
        
    except Exception as e:
        conn.rollback()
        print(f"Error in leave_group: {str(e)}")
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()
        conn.close()
        
# Add a new endpoint to update group status explicitly
@app.route('/groups/<code>/status', methods=['POST'])
def update_group_status(code):
    data = request.get_json()
    
    if 'status' not in data:
        return jsonify({'error': 'Missing status'}), 400
        
    status = data['status']
    if status not in ['active', 'inactive']:
        return jsonify({'error': 'Invalid status value'}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Update group status
        cursor.execute(
            "UPDATE `group` SET status = %s WHERE code = %s",
            (status, code)
        )
        
        if cursor.rowcount == 0:
            return jsonify({'error': 'Group not found'}), 404
            
        conn.commit()
        
        # Notify clients about status change
        socketio.emit('group_status_update', {'status': status}, room=code)
        
        return jsonify({'message': f'Group status updated to {status}'}), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()
        conn.close()


# Endpoint para iniciar a seleção de restaurantes
@app.route('/groups/<code>/start', methods=['POST'])
def start_restaurant_selection(code):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor1 = conn.cursor()
    try:
        # Check if the group exists
        cursor.execute("SELECT * FROM `group` WHERE code = %s", (code,))
        group = cursor.fetchone()
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
            
        # Check if all members are ready
        cursor.execute(
            "SELECT COUNT(*) as total, SUM(is_ready) as ready FROM group_user WHERE group_code = %s",
            (code,)
        )

        result = cursor.fetchone()
        
        if result['total'] == 0 or result['ready'] < result['total']:
            return jsonify({'error': 'Not all members are ready'}), 400
            
        # Update group status to "selecting"
        cursor.execute(
            "UPDATE `group` SET status = 'selecting' WHERE code = %s",
            (code,)
        )
        conn.commit()

        cursor1.execute('''
            SELECT place_vector, food_vector FROM user WHERE username 
            IN (SELECT username FROM group_user WHERE group_code = %s)
        ''',(code,))

        result = cursor1.fetchall()
        print(result,len(result[0]),len(result[1]))
        #zipped = zip(*result)

#        cursor.execute('''
#            SELECT  history_place_vector, history_food_vector FROM user WHERE username 
#            IN (SELECT username FROM group_user WHERE group_code = %s )
#        ''',(code,))

#        zipped1 = zip(*cursor.fetchall())
        
        place_vector = []
        food_vector = []
        history_place_vector = []
        history_food_vector = []

        temp_place_vector = [result[0][0],result[1][0]]
        temp_food_vector = [result[0][1],result[1][1]]

#        temp_history_place_vector = zipped1[0]
#        temp_history_food_vector = zipped1[1]

        for vector in temp_place_vector:
            place_vector.append(json.loads(vector))
        for vector in temp_food_vector:
            food_vector.append(json.loads(vector))
 #       for vector in temp_history_place_vector:
 #           history_place_vector.append(json.loads(vector))
 #       for vector in temp_history_food_vector:
 #           history_food_vector.append(json.loads(vector))

        place_vector = vect.average_embedding(place_vector)
        food_vector = vect.average_embedding(food_vector)
    
#        history_place_vector = vect.average_embedding(history_place_vector)
#        history_food_vector = vect.average_embedding(history_food_vector)

#        place_vector = [place_vector,history_place_vector]
#        food_vector = [food_vector,history_food_vector]
        
#        place_vector = vect.average_embedding(place_vector)
#        food_vector = vect.average_embedding(food_vector)

        # Emitir evento para todos os membros do grupo
        socketio.emit('selection_started', {
            'group_code': code,
            'message': 'The host has started restaurant selection'
        }, room=code)

        
        cursor1.execute("Set @query_vec = (%s):> VECTOR(4096)",(json.dumps(place_vector),))

        cursor1.execute("SELECT *, place_vector <*> @query_vec AS score FROM restaurant ORDER BY score DESC LIMIT 5")

        restaurants = cursor1.fetchall()

        cursor1.execute("Set @query_vec = (%s):> VECTOR(4096)",(json.dumps(food_vector),))

        cursor1.execute("SELECT *, food_vector <*> @query_vec AS score FROM restaurant ORDER BY score DESC LIMIT 5")

        restaurants = restaurants + cursor1.fetchall()

        restaurants_no_doubles = []
        for item in restaurants:
            if restaurants.count(item) > 1 and item not in restaurants_no_doubles:
                restaurants_no_doubles.append(item)

        out_restaurants = []
        for restaurant in restaurants:
            print(len(restaurant))
            #if len(restaurant) < 14:
             #   continue
            restaurant_id, restaurant_name,rating, url,_,_,price_range_max,price_range_min,price_level,_,_,_,summary,_ = restaurant

            print(restaurant_id)
            cursor.execute("SELECT url FROM photo WHERE restaurant_id = %s LIMIT 1", (restaurant_id,))
            images = cursor.fetchall()
            if price_range_min == 0:
                out_restaurant = {
                'restaurant_name': restaurant_name,
                'rating': rating,
                'url':url,
                'price_level':price_level,
                'summary':summary,
                'images': [img['url'] for img in images],
                'price_range': "" 

            }
            else :
                out_restaurant = {
                    'restaurant_name': restaurant_name,
                    'rating': rating,
                    'url':url,
                    'price_level':price_level,
                    'summary':summary,
                    'images': [img['url'] for img in images],
                    'price_range': "(" + str(price_range_min) + "€-" + str(price_range_max) + "€)" 

                }
            print(out_restaurant['restaurant_name'])
            out_restaurants.append(out_restaurant)

        print("FINALLL \n\n\n\n\n\n")
        
        return jsonify({'restaurants':out_restaurants}), 200

        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor1.close()
        cursor.close()
        conn.close()

# Endpoint to add user preferences
@app.route('/user/<username>/preferences', methods=['GET'])
def get_user_preferences(username):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Validate user exists
        cursor.execute("SELECT username FROM user WHERE username = %s", (username,))
        if not cursor.fetchone():
            return jsonify({'error': 'User not found'}), 404
        
        cursor.execute(
            "SELECT preference FROM user_preference WHERE username = %s",
            (username,)
        )
        
        preferences = [row['preference'] for row in cursor.fetchall()]
        
        return jsonify({'preferences': preferences}), 200
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    finally:
        cursor.close()
        conn.close()

# Endpoint to update user preferences
@app.route('/user/<username>/preferences', methods=['POST'])
def update_user_preferences(username):
    data = request.get_json()
    
    if 'preferences' not in data:
        return jsonify({'error': 'Missing preferences'}), 400
    
    preferences = data['preferences']
    if not isinstance(preferences, list):
        return jsonify({'error': 'Preferences must be a list'}), 400
    

@socketio.on('restaurant_vote')
def handle_restaurant_vote(data):
    """Handle votes for restaurants during group selection"""
    room = data.get('group_code')
    restaurant_id = data.get('restaurant_id')
    username = data.get('username')
    liked = data.get('liked', False)
    
    if not all([room, restaurant_id, username]):
        return
    
    print(f"User {username} {'liked' if liked else 'disliked'} restaurant {restaurant_id} in group {room}")
    
    # Forward vote to all members in the room
    emit('restaurant_vote', data, room=room)
    
    # Store vote in database
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if liked:
            # Store like in database (handle duplicates)
            cursor.execute(
                "INSERT IGNORE INTO user_restaurant (username, restaurant_id) VALUES (%s, %s)",
                (username, restaurant_id)
            )
        else:
            # Remove like if exists
            cursor.execute(
                "DELETE FROM user_restaurant WHERE username = %s AND restaurant_id = %s",
                (username, restaurant_id)
            )
        
        conn.commit()
        
        # Check if this vote created a match
        check_for_restaurant_match(room, restaurant_id)
        
    except Exception as e:
        print(f"Error handling restaurant vote: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

# Endpoint to update user profile
@app.route('/user/<username>/profile', methods=['POST'])
def update_user_profile(username):
    data = request.get_json()
    
    # Check for required fields
    if not data or not any(k in data for k in ('name', 'email')):
        return jsonify({'error': 'No profile data provided'}), 400
def check_for_restaurant_match(group_code, restaurant_id):
    """Check if all group members liked the same restaurant"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Count total members in the group
        cursor.execute(
            "SELECT COUNT(*) as total_members FROM group_user WHERE group_code = %s",
            (group_code,)
        )
        result = cursor.fetchone()
        total_members = result['total_members']
        
        if total_members == 0:
            return
        
        # Count users who liked this restaurant in this group
        cursor.execute("""
            SELECT COUNT(*) as likes_count 
            FROM user_restaurant ur
            JOIN group_user gu ON ur.username = gu.username
            WHERE gu.group_code = %s AND ur.restaurant_id = %s
        """, (group_code, restaurant_id))
        
        result = cursor.fetchone()
        likes_count = result['likes_count']
        
        # If all members liked the restaurant, we have a match!
        if likes_count == total_members:
            print(f"MATCH FOUND! All {total_members} members in group {group_code} liked restaurant {restaurant_id}")
            
            # Get restaurant details
            cursor.execute("SELECT name FROM restaurant WHERE restaurant_id = %s", (restaurant_id,))
            restaurant = cursor.fetchone()
            restaurant_name = restaurant['name'] if restaurant else "Unknown restaurant"
            
            # Emit match event to all group members
            socketio.emit('restaurant_match', {
                'restaurant_id': restaurant_id,
                'restaurant_name': restaurant_name,
                'message': f"Everyone liked {restaurant_name}!"
            }, room=group_code)
            
            # Optionally, update group status to 'matched'
            cursor.execute(
                "UPDATE `group` SET status = 'matched' WHERE code = %s",
                (group_code,)
            )
            conn.commit()
            
    except Exception as e:
        print(f"Error checking for restaurant match: {e}")
    finally:
        cursor.close()
        conn.close()

# Add endpoint to get restaurants for selection
@app.route('/groups/<code>/restaurants', methods=['GET'])
def get_group_restaurants(code):
    """Get restaurants for a group to select from"""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Check if group exists
        cursor.execute("SELECT * FROM `group` WHERE code = %s", (code,))
        group = cursor.fetchone()
        
        if not group:
            return jsonify({'error': 'Group not found'}), 404
        
        # For a real implementation, you would fetch restaurants based on group preferences
        # Here, we'll just get all restaurants with their images
        cursor.execute("""
            SELECT r.*, 
                   (SELECT COUNT(*) FROM user_restaurant ur 
                    JOIN group_user gu ON ur.username = gu.username 
                    WHERE ur.restaurant_id = r.restaurant_id AND gu.group_code = %s) as like_count
            FROM restaurant r
            LIMIT 10
        """, (code,))
        
        restaurants = cursor.fetchall()
        
        # Get images for each restaurant
        for restaurant in restaurants:
            restaurant_id = restaurant['restaurant_id']
            cursor.execute("SELECT url FROM photo WHERE restaurant_id = %s LIMIT 5", (restaurant_id,))
            photos = cursor.fetchall()
            restaurant['photos'] = [photo['url'] for photo in photos]
            
            # Get users who liked this restaurant
            cursor.execute("""
                SELECT ur.username 
                FROM user_restaurant ur
                JOIN group_user gu ON ur.username = gu.username
                WHERE ur.restaurant_id = %s AND gu.group_code = %s
            """, (restaurant_id, code))
            
            likes = cursor.fetchall()
            restaurant['likes'] = [like['username'] for like in likes]
            
            # Convert decimal to float for JSON serialization
            if 'rating' in restaurant:
                restaurant['rating'] = float(restaurant['rating'])
        
        return jsonify({'restaurants': restaurants}), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# Add endpoint to record match result
@app.route('/groups/<code>/match', methods=['POST'])
def record_group_match(code):
    """Record the final restaurant match for a group"""
    data = request.get_json()
    
    if 'restaurant_id' not in data:
        return jsonify({'error': 'Missing restaurant_id'}), 400
        
    restaurant_id = data['restaurant_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if group exists
        cursor.execute("SELECT * FROM `group` WHERE code = %s", (code,))
        if not cursor.fetchone():
            return jsonify({'error': 'Group not found'}), 404
            
        # Update group status to 'matched'
        cursor.execute(
            "UPDATE `group` SET status = 'matched' WHERE code = %s",
            (code,)
        )
        
        # Here you could record additional information about the match
        # For example, store the match in a separate table
        
        conn.commit()
        
        return jsonify({'message': 'Match recorded successfully'}), 200
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/match/<username>',methods=['POST'])
def complete_match(username):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        data = request.get_json()
        restaurant_id = data['restaurant_id']

        cursor.execute("INSERT INTO user_history (username, restaurant_id) VALUES (%s, %s)",username, restaurant_id)

        cursor.execute('''SELECT place_vector, food_vector FROM restaurant WHERE restaurant_id 
                        IN (SELECT restaurant_id FROM user_history WHERE user = %s)''',(username,))
        
        zipped = zip(*cursor.fetchall())
        place_vector = []
        food_vector = []
        temp_place_vector = zipped[0]
        temp_food_vector = zipped[1]
        for vector in temp_place_vector:
            place_vector.append(json.loads(vector))
        for vector in temp_food_vector:
            food_vector.append(json.loads(vector))

        place_vector = vect.average_embbeddings(place_vector)
        food_vector = vect.average_embbeddings(food_vector)
        cursor.execute("UPDATE user SET history_place_vector = %s, history_food_vector = %s, history = history + 1",(place_vector,food_vector,))

    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)