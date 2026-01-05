# Clerk Authentication Setup

## Step 1: Create a Clerk Account

1. Go to [https://dashboard.clerk.com](https://dashboard.clerk.com)
2. Sign up or log in
3. Create a new application

## Step 2: Get Your API Keys

1. In your Clerk dashboard, go to **"API Keys"** in the left sidebar
2. You'll see:
   - **Publishable Key** (starts with `pk_test_` or `pk_live_`)
   - **Secret Key** (starts with `sk_test_` or `sk_live_`)

## Step 3: Configure Your Application

1. In Clerk dashboard, go to **"Configure"** → **"Domains"**
2. Add your development domain: `localhost:3000`
3. For production, add your production domain

## Step 4: Update Environment Variables

Update your `.env.local` file in the frontend directory:

```bash
# In frontend/.env.local
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_your_key_here
CLERK_SECRET_KEY=sk_test_your_key_here
```

**Important Notes:**
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` - Must start with `NEXT_PUBLIC_` to be accessible in the browser
- `CLERK_SECRET_KEY` - Only used server-side (in API routes if needed)
- Restart your Next.js dev server after updating `.env.local`

## Step 5: Test Authentication

1. Start your frontend: `npm run dev`
2. Visit `http://localhost:3000`
3. You should see Clerk's sign-in/sign-up UI

## Troubleshooting

### Error: "Missing publishable key"
- Make sure `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` is set in `.env.local`
- Make sure it starts with `NEXT_PUBLIC_`
- Restart your dev server after adding the key

### Error: "Invalid publishable key"
- Check that you copied the entire key correctly
- Make sure you're using the correct environment (test vs live)

### Sign-in not working
- Check that `localhost:3000` is added to your Clerk application's allowed domains
- Check browser console for errors

