# GuardianAI – Emergency Intake & Face Matching (Direct Supabase Architecture)

This Flutter application provides a streamlined emergency reporting flow with integrated face embedding and similarity matching using Supabase (Postgres + pgvector) — no standalone Node backend required.

## Features

- **Supabase Auth** – email/password signup & login flows powered by `supabase_flutter`.
- **Face capture & embedding** – onboarding flow that captures a selfie via the device camera, sends it to a lightweight DeepFace-based microservice, and stores the resulting embedding in Supabase.
- **Emergency reporting** – users submit emergencies directly into Supabase; the raw JSON payload is preserved in `emergencies.raw_data`.
- **Structured architecture** – domain-specific directories for `core`, `services`, `models`, `screens`, and `widgets` to keep responsibilities separated.
- **Face similarity candidate selection** – after submitting an emergency with an attached image, a 512‑d embedding is generated and top matches from `users.face_embedding` are suggested.

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
2. **Create a Supabase project** with pgvector enabled and the following tables (plus the new `victim_face_embedding` column on `emergencies`):

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
		 id bigserial primary key,
		 source text not null,
		 message text,
		 timestamp timestamptz default timezone('utc', now()),
		 location text,
		 victim_id uuid references public.users (id),
		 victim_face_embedding vector(512), -- embedding captured from submitted image
		 raw_data jsonb
	 );
	 ```

3. **Configure environment variables** in a `.env` file at the project root (client-safe values only):

	 ```env
	 SUPABASE_URL=https://<your-project>.supabase.co
	 SUPABASE_ANON_KEY=<anon-key>
	 EMBEDDING_SERVICE_URL=http://localhost:8000
	 ```

	 The `EMBEDDING_SERVICE_URL` should point to your DeepFace embedding microservice base URL (the app appends `/generate_embedding`).

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

## Face similarity RPC
## Summarizing Service (Optional, ML-Oriented)

The previous hard‑coded rule/triage system was removed. A new ML‑ready pipeline now:

- Extracts document features with spaCy (token stats, lightweight embeddings, regex vitals)  
- Supports training a regression model (Ridge) on real labeled severity data (no synthetic examples committed)  
- Persists artifacts (`severity_model.joblib`, `feature_meta.json`, `thresholds.json`)  
- Provides a graceful heuristic fallback if no trained model exists (so you still see structured output during development)  
- Exposes a `/model_info` endpoint for status & metadata.
 - Optional: environment flag `USE_PRETRAINED_SEVERITY=1` enables a pretrained sentiment (VADER) mapping for severity instead of the heuristic when no trained model is present.

### Run the service

```powershell
cd summarizing_service
pip install -r requirements.txt
# Optional: enable pretrained sentiment-based severity mapping instead of vitals heuristic when untrained
$env:USE_PRETRAINED_SEVERITY = 1
python main.py  # starts on port 8001 by default (env: SUMMARIZING_SERVICE_PORT)
```

Health & status:

```text
GET /health      -> {"status":"ok"}
GET /model_info  -> {"trained": false, "artifacts": {...}, "fallback_active": true, ...}
```

Summarization:

```
POST /summarize
Body: { "description": "<free text>", "vitals": {..}, "history": [..] }
```

Response (fallback example when untrained):
```json
{
	"severity_score": 4.0,
	"summary": {
		"vitals": {"bp_systolic": 82, "bp_diastolic": 55},
		"token_stats": {"length": 54, "exclaim_count": 0, "word_count": 11},
		"entities": [],
		"raw_description": "82/55 dizzy and pale"
	},
	"category": "Urgent",
	"reasons": ["Low systolic 82"]
}
```

After training, reasons will shift to feature contribution explanations derived from the learned linear model coefficients.

If you set `USE_PRETRAINED_SEVERITY=1` (and have not trained a model), severity is computed from VADER sentiment compound score mapped inversely to 0–10 (negative = higher severity). Reasons will show the sentiment compound value.

### Training the severity model

Prepare a CSV (real labeled data only) with columns, for example:

```
text,severity_score
"82/55 dizzy and pale",6.5
"Minor ankle twist walking",1.5
...
```

Run training:

```powershell
cd summarizing_service
pip install -r requirements.txt
python guardian_cli.py --train --data dataset.csv --text-col text --score-col severity_score
```

Artifacts will be written to `summarizing_service/artifacts/` and immediately used by the running service (restart if already running without model loaded). `thresholds.json` is derived from empirical score quantiles to separate Non-Urgent / Urgent / Critical.

Predict via CLI (after training):

```powershell
python guardian_cli.py --text "Patient reports sudden vision loss and severe headache hr 118"
```

Pretty JSON:

```powershell
python guardian_cli.py --file sample.txt --pretty
```

### Adding summary columns (if storing results)

```sql
alter table public.emergencies
	add column if not exists summary_data jsonb,
	add column if not exists severity_score real;
```

### Interpretation Notes

- Fallback heuristic = temporary; not medical advice; replace ASAP with trained model.
- Feature list and thresholds available at `/model_info` for transparency.
- Ridge regression output clamped to 0–10 for downstream UI consistency.

### Extending

- Add new vitals extraction patterns in `summarizing_service/config/patterns.json` (regex only, keeps code clean).
- Swap regression estimator (e.g. ElasticNet) without changing endpoint contact.
- Introduce calibration on severity score distribution once enough data accrues.

Enable the function for retrieving candidate matches (cosine similarity):

```sql
create or replace function public.find_similar_faces(
  query vector(512),
  match_limit int default 5
)
returns table (
  user_id uuid,
  name text,
  similarity float4
)
language sql stable as $$
  select
    u.id as user_id,
    u.name,
    1 - (u.face_embedding <=> query) as similarity
  from public.users u
  where u.face_embedding is not null
  order by u.face_embedding <=> query
  limit match_limit;
$$;
```

## Testing

```powershell
flutter analyze
flutter test
```

The widget test bootstraps Supabase with mock dependencies and verifies the login screen renders when unauthenticated.

## Next steps

- Add RLS-safe listing strategy or dedicated RPC for retrieving user display names for matched candidates.
- Add optional embedding authentication (API key header) to the embedding service.
- Implement caching or batching if embedding latency becomes a bottleneck.
- Integrate Realtime to stream new emergencies to an admin dashboard.

---

Happy building! GuardianAI is on its way to providing rapid, AI-assisted emergency intake and identity verification.
