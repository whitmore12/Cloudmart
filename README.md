#README.md created by Howard Ames III

# Cloud-Mart

A cloud-based campus marketplace for Hampton University students.

# Deployed Link
https://cloudmart-five.vercel.app/

## Prerequisites

- **Python 3.10+** installed
- **The EC2 SSH key file** (`ec2Test.pem`) — required for database connection

## Setup Instructions

### 1. Clone the repository

```bash
git clone https://github.com/kwam12/Cloudmart.git
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

### 3. Activate the virtual environment

**macOS/Linux:**
```bash
source venv/bin/activate
```

**Windows:**
```bash
venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

If it does not work, install manually:
```bash
pip install flask flask-cors sshtunnel psycopg bcrypt python-dotenv boto3
```

### 5. Run the application

```bash
python app.py
```

The server will start at **http://localhost:5001**

### 6. Access the Application

Open your browser and copy the file path of where your Signin.html is and paste it into the broswer*

| Page | URL |
|------|-----|
| **Sign In / Register** | Frontend/Signin.html |
| **Marketplace (Home)** | Frontend/index.html |
| **Create Listing** | Frontend/create.html |
| **My Wishlist** | Frontend/wishlist.html |

## Features

- **User Authentication** - Register with Hampton email (@my.hamptonu.edu) and sign in
- **Browse Listings** - View all marketplace items with search and category filters
- **Create Listings** - Sell items with image upload to AWS S3
- **Wishlist** - Save items by clicking the heart ❤️ button
- **Shopping Cart** - Add items to cart for checkout

## Project Structure

```
CMFINAL/
├── app.py                 # Flask backend server & API routes
├── auth.py                # Authentication utilities
├── s3_config.py           # AWS S3 configuration
├── requirements.txt       # Python dependencies
├── docker-compose.yml     # Local PostgreSQL (optional)
├── Frontend/
│   ├── index.html         # Marketplace/Home page
│   ├── Signin.html        # Login/Register page
│   ├── create.html        # Create listing page
│   ├── wishlist.html      # User's saved items page
│   ├── styles.css         # Shared styles
│   └── script.js          # Frontend JavaScript
├── DataBase/
│   ├── postgres.py        # Database connection module
│   ├── 01_schema.sql      # Database schema
│   └── 02_seed.sql        # Seed data
└── Resources/
    ├── ec2Test.pem        # SSH key (not in Git)
    └── Images/            # Static images
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user |
| POST | `/api/auth/login` | User login |
| GET | `/api/listings` | Get all listings |
| POST | `/api/listings` | Create new listing |
| GET | `/api/wishlist?user_id=X` | Get user's wishlist |
| POST | `/api/wishlist` | Add to wishlist |
| DELETE | `/api/wishlist/:id?user_id=X` | Remove from wishlist |
| POST | `/api/uploads/presign` | Get S3 presigned URL |

## Configuration

| Setting | Value |
|---------|-------|
| Backend Port | `5001` |
| Database | AWS RDS PostgreSQL |
| Image Storage | AWS S3 |

## Quick Start Checklist

- [ ] Python 3.10+ installed
- [ ] Project files cloned/copied
- [ ] `Resources/ec2Test.pem` file present
- [ ] Virtual environment created and activated
- [ ] Dependencies installed
- [ ] Run with `python app.py`
- [ ] Open http://localhost:5001 in browser

## Troubleshooting

**Port 5001 already in use:**
```bash
# Find and kill the process using port 5001
lsof -i :5001
kill -9 <PID>
```

**SSH key permission error:**
```bash
chmod 600 Resources/ec2Test.pem
```

**Database connection failed:**
- Ensure you have internet access
- Verify the `ec2Test.pem` file is in the correct location
- Check that the EC2 instance is running

**Module not found errors:**
```bash
pip install flask flask-cors sshtunnel psycopg bcrypt python-dotenv boto3
```

# Cloudmart
