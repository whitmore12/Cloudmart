# Elastic Beanstalk Deployment Checklist

## Required Environment Variables (Set in EB Console > Configuration > Software > Environment Properties)

### Database (RDS) - Auto-populated if RDS attached to EB
- `RDS_HOSTNAME` - RDS endpoint (auto-set by EB)
- `RDS_PORT` - 5432 (auto-set by EB)
- `RDS_DB_NAME` - Database name (auto-set by EB)
- `RDS_USERNAME` - Master username (auto-set by EB)
- `RDS_PASSWORD` - Master password (auto-set by EB)

### Application Configuration
- `USE_SSH_TUNNEL` = `false` **(Critical - must be false for production)**
- `APP_BASE_URL` = `https://your-eb-env.elasticbeanstalk.com` (your EB URL)
- `ADMIN_BOOTSTRAP_TOKEN` = `your-secure-random-token` (for initial admin setup)

### Email (SMTP)
- `SMTP_USER` = `your-gmail@gmail.com`
- `SMTP_PASSWORD` = `your-gmail-app-password` (not regular password)

### AWS/S3
- `AWS_REGION` = `us-east-1` (or your region)
- `BUCKET_NAME` = `your-s3-bucket-name`
- `AWS_ACCESS_KEY_ID` = *(optional - leave blank to use IAM role)*
- `AWS_SECRET_ACCESS_KEY` = *(optional - leave blank to use IAM role)*

### IAM Role for EB (if not using AWS keys)
Ensure your EB instance profile has:
- `AmazonS3FullAccess` (or scoped to your bucket)
- `AmazonRDSFullAccess` (if needed)

## Deployment Steps

1. **Commit all changes:**
   ```bash
   git add .
   git commit -m "Fix EB deployment: Procfile, health check, .ebextensions"
   ```

2. **Deploy:**
   ```bash
   eb deploy cloudmart-env
   ```

3. **Verify deployment:**
   - Check EB console > Health > Should be "Ok"
   - Visit `https://your-env.elasticbeanstalk.com/api/health` - should return `{"status": "healthy", "database": "connected"}`
   - Visit main URL - should load frontend

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| 502 Bad Gateway | Check `eb logs` - usually wrong WSGI path or port |
| Database connection failed | Verify RDS security group allows EB security group on port 5432 |
| Static files 404 | Ensure `.ebextensions/03_static_files.config` is deployed |
| Health check failing | Verify `/api/health` endpoint returns 200 |
| Email not working | Verify SMTP credentials, use Gmail App Password |

## Debugging Commands

```bash
# View recent logs
eb logs

# SSH into instance (if enabled)
eb ssh

# Check environment variables on instance
eb ssh -c "env | grep -E '(RDS|DB|USE_SSH|APP_BASE|SMTP|AWS|BUCKET)'"

# Restart app server
eb ssh -c "sudo systemctl restart web"
```

## Key Fixes Applied

1. **Procfile**: Changed `application:application` → `application:app` (correct Flask app name)
2. **Port binding**: Changed hardcoded `8000` → `$PORT` (EB sets this dynamically)
3. **Health check**: Added `/api/health` endpoint for ALB health checks
4. **Database init**: Now runs on gunicorn startup (not just `__main__`)
5. **SSH tunnel**: Defaults to `false` via `.ebextensions` config
6. **Static files**: Configured nginx to serve `/Resources/` and `/Frontend/`
7. **.ebignore**: Excludes venv, tests, local configs from deployment bundle