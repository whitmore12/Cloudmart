# eCamp

A cloud-based campus marketplace for Hampton University students.

# Deployed Link
http://cloudmart-env.eba-wbku2kbr.us-east-1.elasticbeanstalk.com/index.html

> The URL above is a placeholder. After `eb create` it will be the
> environment URL printed by the EB CLI (for example
> `ecamp-env.us-east-1.elasticbeanstalk.com`).


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
python application.py
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




## Configuration

| Setting | Value |
|---------|-------|
| Backend Port | `5001` |
| Database | AWS RDS PostgreSQL |
| Image Storage | AWS S3 |


## Deploying to Elastic Beanstalk (eCamp)

### 1. One-time AWS setup (new account)

```bash
aws configure                      # new account access key
aws s3 mb s3://ecamp-images-<unique-suffix> --region us-east-1
```

Keep the bucket private; the Flask backend streams images through
`/api/listing-images/...` and `/api/profile-images/...`.

Create an RDS PostgreSQL instance (free-tier: `db.t3.micro`, 20 GB,
single-AZ) in the same VPC as Elastic Beanstalk:

- DB name: `ecamp`
- Master username: `ecamp`
- Allow port `5432` from the EB environment's security group.

### 2. Create the EB application and environment

```bash
eb init ecamp --platform python-3.11 --region us-east-1
eb create ecamp-env --single
```

### 3. Set environment properties (secrets live here, not in Git)

```bash
eb setenv \
  AWS_REGION=us-east-1 \
  USE_SSH_TUNNEL=false \
  BUCKET_NAME=ecamp-images-<unique-suffix> \
  DB_HOST=<rds-endpoint> \
  DB_NAME=ecamp \
  DB_USER=ecamp \
  DB_PASSWORD=<db-password> \
  ADMIN_BOOTSTRAP_TOKEN=<random-token> \
  SMTP_USER=<gmail-address> \
  SMTP_PASSWORD=<gmail-app-password> \
  APP_BASE_URL=http://ecamp-env.us-east-1.elasticbeanstalk.com
```

Grant the EB EC2 instance profile (`aws-elasticbeanstalk-ec2-role`)
`s3:GetObject`, `s3:PutObject` and `s3:DeleteObject` on the bucket. No AWS
access keys are needed on the instance.

### 4. Deploy

```bash
eb deploy ecamp-env
eb status ecamp-env        # green/Ready
eb logs                    # if it fails
```

### 5. Database schema

The schema is created automatically by `init_db()` on the first database
connection, so a brand-new empty database needs no manual SQL. Existing
data can be copied with:

```bash
pg_dump -h <old-host> -U <old-user> -d <old-db> --no-owner --no-acl -Fc -f ecamp.dump
pg_restore -h <new-rds-endpoint> -U ecamp -d ecamp --no-owner --no-acl ecamp.dump
```

`init_db()` adds any newer columns (`pirate_dollars`, `transactions`,
`password_resets`, etc.) on the next connection.

> `Resources/*.pem` and `venv/` are excluded from the EB bundle by
> `.ebignore`. Do not re-add private keys to the repository; rotate any key
> that has already been committed.

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

# eCamp
