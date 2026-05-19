# DEPLOYING THE AUTOMAT HUB ON RAILWAY
# Complete plain-language step-by-step guide
# Both backend API and frontend served together

---

## WHAT RAILWAY IS

Railway is a hosting platform that runs your code in the cloud.
Think of it like renting a computer that is always switched on.
Your backend API and frontend pages run on Railway.
Users access everything from one URL like: https://yourapp.railway.app

---

## BEFORE YOU START — What You Need

1. Your code (the automat_hub folder) on your computer
2. A free Railway account
3. A free GitHub account
4. Paystack account (for payments)
5. About 30 minutes

---

## STEP 1 — Put Your Code on GitHub

GitHub is where Railway fetches your code from.
Think of it as cloud storage for code.

### 1a. Create a GitHub account
Go to: https://github.com
Click Sign Up and create a free account.

### 1b. Create a new repository
After logging in to GitHub:
1. Click the + icon at the top right
2. Click New repository
3. Name it: automat-hub
4. Leave it Private (recommended)
5. Click Create repository

### 1c. Upload your code

Open a terminal (Command Prompt on Windows) in your automat_hub folder.
Type these commands one at a time:

    git init
    git add .
    git commit -m "Initial commit - The Automat Hub"
    git branch -M main
    git remote add origin https://github.com/YOURUSERNAME/automat-hub.git
    git push -u origin main

Replace YOURUSERNAME with your actual GitHub username.
When asked for password, use a Personal Access Token from:
https://github.com/settings/tokens → Generate new token → check repo

---

## STEP 2 — Create a Railway Account

1. Go to: https://railway.app
2. Click Login → Continue with GitHub
3. Authorize Railway to access your GitHub

You are now logged in to Railway.

---

## STEP 3 — Create a New Project on Railway

1. On the Railway dashboard, click: New Project
2. Click: Deploy from GitHub repo
3. Click: Configure GitHub App → Install Railway
4. Select your automat-hub repository
5. Click: Deploy Now

Railway will start trying to build your project.
Wait about 2 minutes. It will fail at first because you have not set up the database yet. That is normal. Continue to the next step.

---

## STEP 4 — Add PostgreSQL Database

1. On your Railway project page, click the + button (Add Service)
2. Click: Database
3. Click: Add PostgreSQL
4. Railway creates a PostgreSQL database automatically

Railway automatically adds a DATABASE_URL variable to your project.
You do not need to do anything else for the database connection.

---

## STEP 5 — Add Redis

1. Again click the + button
2. Click: Database  
3. Click: Add Redis

Railway automatically adds a REDIS_URL variable.

---

## STEP 6 — Set Your Environment Variables

This is the most important step. Click on your main app service (not the database) then click the Variables tab.

Add each variable by clicking + Add Variable:

### REQUIRED (Without these, nothing works)

Variable name: SECRET_KEY
Value: Run this in your terminal to generate one:
python -c "import secrets; print(secrets.token_hex(32))"
Copy the output and paste it as the value.

Variable name: API_KEY
Value: Run this:
python -c "import secrets; print(secrets.token_hex(16))"
Copy and paste.

Variable name: ENVIRONMENT
Value: production

### PAYSTACK (For payments)
Get these from: https://dashboard.paystack.com/#/settings/developer

Variable name: PAYSTACK_SECRET_KEY
Value: sk_live_xxxxxxxxxx (use sk_test_ while testing)

Variable name: PAYSTACK_PUBLIC_KEY
Value: pk_live_xxxxxxxxxx (use pk_test_ while testing)

### TWILIO (For SMS alerts - optional to start)
Get from: https://console.twilio.com

Variable name: TWILIO_ACCOUNT_SID
Value: ACxxxxxxxxxx

Variable name: TWILIO_AUTH_TOKEN
Value: your_auth_token

Variable name: TWILIO_PHONE_NUMBER
Value: +1234567890

### AWS S3 (For photo storage - optional to start)
Get from: https://aws.amazon.com/iam

Variable name: AWS_ACCESS_KEY_ID
Value: AKIAxxxxxxxxxx

Variable name: AWS_SECRET_ACCESS_KEY
Value: your_secret_key

Variable name: AWS_BUCKET_NAME
Value: automat-hub-production

Variable name: AWS_REGION
Value: eu-west-1

### SENDGRID (For emails - optional to start)
Get from: https://sendgrid.com

Variable name: SENDGRID_API_KEY
Value: SG.xxxxxxxxxx

Variable name: FROM_EMAIL
Value: noreply@automatcorp.org.ng

Variable name: FROM_NAME
Value: The Automat Hub

### FIREBASE (For mobile push notifications - optional to start)
Get from: https://console.firebase.google.com

Variable name: FIREBASE_PROJECT_ID
Value: your-project-id

---

## STEP 7 — Run the Database Migrations

Your database is empty. You need to create the tables.

### Option A: Railway CLI (Easiest)

Install Railway CLI:

    npm install -g @railway/cli

Login:

    railway login

Connect to your project:

    railway link

Run migrations (this connects to your Railway database directly):

    railway run psql $DATABASE_URL -f database/migrations/001_create_dcp_tables.sql
    railway run psql $DATABASE_URL -f database/migrations/002_create_escrow_tables.sql

### Option B: Railway Console

1. On your Railway project, click on the PostgreSQL service
2. Click Data → Query
3. Copy the entire contents of database/migrations/001_create_dcp_tables.sql
4. Paste into the query box and click Run
5. Do the same for 002_create_escrow_tables.sql

---

## STEP 8 — Redeploy

After setting variables and running migrations:
1. Click on your main app service
2. Click Deployments tab
3. Click the three dots on the latest deployment
4. Click Redeploy

Wait 2-3 minutes for deployment to complete.

---

## STEP 9 — Get Your Live URL

1. On your main app service, click Settings
2. Under Networking, click Generate Domain
3. Railway gives you a URL like: https://automat-hub-production.railway.app
4. Click the URL to open it

You should see the Automat Hub homepage.

---

## STEP 10 — Connect Your Frontend to the Backend

The frontend and backend are already on the same server on Railway.
The config.js file automatically detects this.

Open frontend/shared/config.js and verify this line:
    API_URL: window.location.hostname === 'localhost' ...

On Railway, window.location.hostname will NOT be localhost,
so it will automatically use '' (empty string = same server).
This means your frontend talks to the backend automatically.

---

## STEP 11 — Update Your Google Maps Key

Find and replace YOUR_GOOGLE_MAPS_KEY_HERE in:
    frontend/fleet/index.html
    frontend/fleet/dashboard.html

Get your key from: https://console.cloud.google.com → APIs → Maps JavaScript API

After updating, commit and push to GitHub:
    git add .
    git commit -m "Update Maps API key"
    git push

Railway auto-deploys when you push to GitHub.

---

## STEP 12 — Add Your Custom Domain (Optional)

To use automatcorp.org.ng instead of the railway.app URL:

1. In Railway → your service → Settings → Networking
2. Click Add Custom Domain
3. Type: automatcorp.org.ng
4. Railway shows you a CNAME record to add

Go to your domain registrar (Namecheap, GoDaddy etc):
5. Add a CNAME record:
   Host: @
   Value: the Railway CNAME value they showed you
6. Wait 10-30 minutes for DNS to update

---

## ALL AVAILABLE URLS AFTER DEPLOYMENT

When deployed to Railway, all these URLs work:

Homepage:
    https://yourapp.railway.app/

API Documentation (all endpoints listed):
    https://yourapp.railway.app/docs

Admin Dashboard:
    https://yourapp.railway.app/frontend/admin/index.html

Fleet Dashboard:
    https://yourapp.railway.app/frontend/fleet/index.html

Private User Dashboard:
    https://yourapp.railway.app/frontend/user/index.html

Inspector App:
    https://yourapp.railway.app/frontend/inspector/index.html

Reseller Portal:
    https://yourapp.railway.app/frontend/reseller/index.html

Workshop Portal:
    https://yourapp.railway.app/frontend/workshop/index.html

Login:
    https://yourapp.railway.app/frontend/auth/login.html

Register:
    https://yourapp.railway.app/frontend/auth/register.html

DCP Verification (public - no login needed):
    https://yourapp.railway.app/frontend/pages/verify.html

Escrow Status (public):
    https://yourapp.railway.app/frontend/pages/escrow.html

---

## FIRST TIME SETUP — Create Your Admin Account

After deployment, you need to create your first admin account.
The backend has pre-loaded inspector credentials in routers/auth.py.

For the admin account, use the API docs at /docs:
1. Go to: https://yourapp.railway.app/docs
2. Find POST /auth/register
3. Click Try it out
4. Fill in your details with role: "admin"
5. Click Execute

NOTE: After creating the first admin, update your backend code to
restrict admin registration (only admins should create admin accounts).
For now, manually set the role in the database.

---

## MAKING CHANGES AFTER DEPLOYMENT

Every time you change any file (backend or frontend):

    git add .
    git commit -m "Description of what you changed"
    git push

Railway automatically detects the push and redeploys.
New version is live in about 2-3 minutes.

---

## IF SOMETHING GOES WRONG

### Deployment fails:
Click Deployments → click the failed deployment → click View Logs
Read the error message. Common issues:
- Missing environment variable (add it in Variables tab)
- Python syntax error in your code
- Missing package in requirements.txt

### 500 Internal Server Error:
Check logs for the error message.
Most likely cause: a missing environment variable.

### Frontend pages not loading:
Make sure frontend/ folder is in your GitHub repo.
Check that StaticFiles mount in main.py is working.

### Database connection error:
Railway auto-provides DATABASE_URL when you add PostgreSQL.
Check it appears in your Variables tab.

### Login not working:
Run the database migrations (Step 7).
Tables need to exist before users can register.

---

## RAILWAY COSTS

Railway has a free tier that includes:
- $5 free credit per month
- PostgreSQL database (small)
- Redis
- Auto-sleep after inactivity (free tier only)

The free $5 covers about 500 hours of runtime.
For 24/7 production use, upgrade to the Hobby plan ($5-20/month).

When your first customers sign up, the revenue covers hosting easily.

---

## CONNECTING THE MOBILE APP TO RAILWAY

In the mobile app's api.ts file, update:
    const API_URL = 'https://yourapp.railway.app';

Replace yourapp with your actual Railway subdomain.
That is the only change needed. The mobile app talks to the same API.

