# GuardianAI – Intake & Identity Module

This Flutter application implements the first half of the GuardianAI workflow, focusing on authentication, face registration, and realtime groundwork for emergency intake.

## Features

- **Supabase Auth** – email/password signup & login flows powered by `supabase_flutter`.
- **Face capture & embedding** – onboarding flow that captures a selfie via the device camera, sends it to a lightweight DeepFace-based microservice, and stores the resulting embedding in Supabase.
- **Emergency reporting** – dashboard entry point lets guardians submit manual emergency reports that are logged through the Node/Express webhook service.
- **Structured architecture** – domain-specific directories for `core`, `services`, `models`, `screens`, and `widgets` to keep responsibilities separated.
- **Realtime-ready dashboard** – placeholder dashboard prepared for incoming emergency events and victim identification workflows.

## Project structure (`lib/`)

```
core/
	app.dart              # MaterialApp + routing
	bootstrap.dart        # Loads .env and initializes Supabase
models/
	app_user.dart         # Freezed model representing app user and serialization
services/
	auth/                 # Auth providers + service wrappers
	embedding/            # REST client for the ONNX embedding microservice
	emergency/            # Guardian emergency webhook client and state providers
	profile/              # Supabase profile persistence and pgvector hookups
screens/
	auth/                 # Login & signup UI with hooks_riverpod
	capture/              # Camera-based face capture workflow
	dashboard/            # Authenticated landing page (placeholder)
	emergency/            # Emergency reporting flow
widgets/                # Reserved for reusable UI components
```

## Getting started

1. **Install Flutter** (3.19+) and ensure you can run `flutter doctor` without issues.
2. **Create a Supabase project** with pgvector enabled and the following tables:

	 ```sql
	 create extension if not exists vector;

	 create table public.users (
		 id uuid primary key,
		 name text,
		 phone text,
		 contacts jsonb,
		 face_embedding vector(512),
		 created_at timestamptz default timezone('utc', now())
	 );

	 create table public.emergencies (
		 id serial primary key,
		 source text,
		 message text,
		 timestamp timestamptz default timezone('utc', now()),
		 location text,
		 victim_id uuid references public.users (id),
		 raw_data jsonb
	 );
	 ```

3. **Configure environment variables** in a `.env` file at the project root:

	 ```env
	 SUPABASE_URL=https://<your-project>.supabase.co
	 SUPABASE_ANON_KEY=<anon-key>
	 EMBEDDING_SERVICE_URL=http://localhost:8000/generate_embedding
	 EMERGENCY_WEBHOOK_URL=http://localhost:4000/twilio/emergency
	 ```

	 The `EMBEDDING_SERVICE_URL` should point to your DeepFace embedding microservice (see below) and `EMERGENCY_WEBHOOK_URL` should target the Express webhook (see "Emergency webhook service").

4. **Install dependencies**

	 ```powershell
	 flutter pub get
	 ```

5. **Generate code** (Freezed / JSON serializable)

	 ```powershell
	 dart run build_runner build --delete-conflicting-outputs
	 ```

6. **Run the app**

	 ```powershell
	 flutter run
	 ```

	 The signup flow will transition to the face capture screen after account creation.

## Embedding microservice (DeepFace)

An implementation is provided under `embedding_service/` using FastAPI + DeepFace. Follow the embedded README to create a virtual environment, install dependencies, and run:

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000
```

The server exposes both `/generate_embedding` (the default expected by the Flutter app) and `/generate_embeddings` as a plural alias. If you deploy your own variant (Node, Edge Function, etc.), make sure it exposes:

```
POST /generate_embedding
Body: { "image_base64": "..." }
Response: { "embedding": [float, float, ...] }
```

The Flutter client (`EmbeddingService`) sends JPEG bytes encoded in base64 and expects a 512-dimension embedding array (default `Facenet512`).

## Emergency webhook service (Node/Express)

The `backend/` folder hosts an Express router that normalizes Twilio webhook payloads (SMS, WhatsApp, voice) into a structured JSON object and persists it to Supabase. A minimal server is provided so you can run it locally:

```powershell
cd backend
npm install
npm start
```

Configure the following environment variables before starting the server:

- `PORT` (optional, defaults to `4000`)
- `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`

Point Twilio webhooks to `https://<your-host>/twilio/emergency`. The Flutter app also uses the same endpoint (via `EMERGENCY_WEBHOOK_URL`) to submit manual reports from the dashboard.

## Twilio webhook & emergencies roadmap

- Implement a Supabase Edge Function or Node backend that receives Twilio SMS/WhatsApp/Call webhooks.
- On incoming messages, insert into the `emergencies` table and use Supabase Realtime to stream into the Flutter dashboard.
- When a new emergency is reviewed, capture victim face via the existing flow, call the embedding service, and run a pgvector similarity query:

	```sql
	select
		id,
		1 - (face_embedding <=> $1::vector(512)) as similarity
	from users
	order by face_embedding <=> $1::vector(512)
	limit 5;
	```

- Use the response to build the unified emergency JSON payload:

	```json
	{
		"source": "sms",
		"timestamp": "2025-10-04T12:00:00Z",
		"location": "San Francisco, CA",
		"raw_message": "Please help me",
		"possible_victims": [
			{ "id": "...", "similarity_score": 0.93 },
			{ "id": "...", "similarity_score": 0.89 }
		]
	}
	```

## Testing

```powershell
flutter analyze
flutter test
```

The widget test bootstraps Supabase with mock dependencies and verifies the login screen renders when unauthenticated.

## Next steps

- Implement Twilio webhook listener and realtime feed.
- Build embeddings store + similarity search function on Supabase (RPC or edge function).
- Flesh out dashboard with emergency list, victim confirmation UI, and JSON export.
- Harden embedding service with authentication, batching, and performance profiling (<100 ms target per inference).

---

Happy building! GuardianAI is on its way to providing rapid, AI-assisted emergency intake and identity verification.
