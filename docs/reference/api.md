# API Documentation
## Vibe-Quality-Searcharr REST API

**Base URL:** `http://localhost:7337/api`
**Version:** 0.1.0
**Authentication:** Bearer JWT Token

---

## Quick Start

### 1. Create Admin Account (Setup)

```bash
POST /api/auth/setup
Content-Type: application/json

{
  "username": "admin",
  "email": "admin@example.com",
  "password": "SecurePassword123!",
  "confirm_password": "SecurePassword123!"
}
```

### 2. Login

```bash
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=SecurePassword123!
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900
}
```

### 3. Use Token

```bash
GET /api/instances/
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## Authentication Endpoints

### POST /api/auth/setup

**Description:** Create initial admin user (first-run only)

**Request:**
```json
{
  "username": "admin",
  "email": "admin@example.com",
  "password": "SecurePassword123!",
  "confirm_password": "SecurePassword123!"
}
```

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Admin user created successfully"
}
```

**Errors:**
- `400 Bad Request` - Setup already completed
- `422 Validation Error` - Invalid input

---

### POST /api/auth/login

**Description:** Authenticate and receive tokens

**Request:**
```
Content-Type: application/x-www-form-urlencoded

username=admin&password=SecurePassword123!
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbG...",
  "refresh_token": "eyJhbG...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "is_active": true,
    "is_superuser": true,
    "totp_enabled": false,
    "created_at": "2026-02-24T12:00:00Z"
  }
}
```

**Errors:**
- `401 Unauthorized` - Invalid credentials
- `429 Too Many Requests` - Rate limit exceeded

---

### POST /api/auth/refresh

**Description:** Refresh access token using refresh token

**Request:**
```json
{
  "refresh_token": "eyJhbG..."
}
```

**Response:** `200 OK`
```json
{
  "access_token": "eyJhbG...",
  "token_type": "bearer",
  "expires_in": 900
}
```

---

### POST /api/auth/logout

**Description:** Invalidate current session

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

---

### GET /api/auth/me

**Description:** Get current user information

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "id": 1,
  "username": "admin",
  "email": "admin@example.com",
  "is_active": true,
  "is_superuser": true,
  "totp_enabled": false,
  "created_at": "2026-02-24T12:00:00Z",
  "last_login": "2026-02-24T14:30:00Z",
  "last_login_ip": "192.168.1.100"
}
```

---

## Instance Endpoints

### POST /api/instances/

**Description:** Create new Sonarr/Radarr instance

**Headers:** `Authorization: Bearer <token>`

**Request:**
```json
{
  "name": "Main Sonarr",
  "instance_type": "sonarr",
  "base_url": "http://localhost:8989",
  "api_key": "your-sonarr-api-key"
}
```

**Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Main Sonarr",
  "instance_type": "sonarr",
  "base_url": "http://localhost:8989",
  "is_active": true,
  "created_at": "2026-02-24T12:00:00Z",
  "last_sync": null
}
```

**Errors:**
- `400 Bad Request` - Duplicate name or invalid data
- `422 Validation Error` - Invalid instance type or URL

---

### GET /api/instances/

**Description:** List all instances for current user

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "name": "Main Sonarr",
    "instance_type": "sonarr",
    "base_url": "http://localhost:8989",
    "is_active": true,
    "created_at": "2026-02-24T12:00:00Z",
    "last_sync": "2026-02-24T14:00:00Z"
  },
  {
    "id": 2,
    "name": "Main Radarr",
    "instance_type": "radarr",
    "base_url": "http://localhost:7878",
    "is_active": true,
    "created_at": "2026-02-24T12:05:00Z",
    "last_sync": "2026-02-24T14:00:00Z"
  }
]
```

---

### GET /api/instances/{id}

**Description:** Get specific instance details

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Main Sonarr",
  "instance_type": "sonarr",
  "base_url": "http://localhost:8989",
  "is_active": true,
  "created_at": "2026-02-24T12:00:00Z",
  "last_sync": "2026-02-24T14:00:00Z",
  "stats": {
    "total_series": 150,
    "monitored_series": 120,
    "missing_episodes": 45
  }
}
```

**Errors:**
- `404 Not Found` - Instance not found or belongs to another user

---

### PATCH /api/instances/{id}

**Description:** Update instance configuration

**Headers:** `Authorization: Bearer <token>`

**Request:**
```json
{
  "name": "Updated Sonarr Name",
  "is_active": false
}
```

**Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Updated Sonarr Name",
  "instance_type": "sonarr",
  "base_url": "http://localhost:8989",
  "is_active": false,
  "created_at": "2026-02-24T12:00:00Z",
  "last_sync": "2026-02-24T14:00:00Z"
}
```

---

### DELETE /api/instances/{id}

**Description:** Delete instance

**Headers:** `Authorization: Bearer <token>`

**Response:** `204 No Content`

---

### POST /api/instances/{id}/test

**Description:** Test instance connection

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "success": true,
  "version": "3.0.9.1549",
  "response_time_ms": 45
}
```

**Errors:**
- `400 Bad Request` - Connection failed

---

## Search Queue Endpoints

### POST /api/search-queues/

**Description:** Create new search queue

**Headers:** `Authorization: Bearer <token>`

**Request:**
```json
{
  "name": "Missing Episodes - Daily",
  "instance_id": 1,
  "strategy": "missing",
  "max_items_per_run": 20,
  "is_active": true,
  "is_recurring": true,
  "schedule": "0 2 * * *"
}
```

**Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Missing Episodes - Daily",
  "instance_id": 1,
  "strategy": "missing",
  "max_items_per_run": 20,
  "is_active": true,
  "is_recurring": true,
  "schedule": "0 2 * * *",
  "status": "idle",
  "created_at": "2026-02-24T12:00:00Z",
  "last_run": null,
  "next_run": "2026-02-25T02:00:00Z"
}
```

---

### GET /api/search-queues/

**Description:** List all search queues for current user

**Headers:** `Authorization: Bearer <token>`

**Query Parameters:**
- `instance_id` (optional): Filter by instance
- `is_active` (optional): Filter by active status

**Response:** `200 OK`
```json
[
  {
    "id": 1,
    "name": "Missing Episodes - Daily",
    "instance_id": 1,
    "instance_name": "Main Sonarr",
    "strategy": "missing",
    "max_items_per_run": 20,
    "is_active": true,
    "status": "idle",
    "last_run": "2026-02-24T02:00:00Z",
    "next_run": "2026-02-25T02:00:00Z"
  }
]
```

---

### GET /api/search-queues/{id}

**Description:** Get search queue details

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "id": 1,
  "name": "Missing Episodes - Daily",
  "instance_id": 1,
  "instance_name": "Main Sonarr",
  "strategy": "missing",
  "max_items_per_run": 20,
  "is_active": true,
  "is_recurring": true,
  "schedule": "0 2 * * *",
  "status": "idle",
  "created_at": "2026-02-24T12:00:00Z",
  "last_run": "2026-02-24T02:00:00Z",
  "next_run": "2026-02-25T02:00:00Z",
  "stats": {
    "total_runs": 10,
    "successful_runs": 9,
    "failed_runs": 1,
    "total_items_found": 125,
    "success_rate": 90.0
  }
}
```

---

### PATCH /api/search-queues/{id}

**Description:** Update search queue

**Headers:** `Authorization: Bearer <token>`

**Request:**
```json
{
  "max_items_per_run": 30,
  "is_active": false
}
```

**Response:** `200 OK`

---

### DELETE /api/search-queues/{id}

**Description:** Delete search queue

**Headers:** `Authorization: Bearer <token>`

**Response:** `204 No Content`

---

### POST /api/search-queues/{id}/start

**Description:** Manually start queue execution

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Search queue started",
  "queue_id": 1,
  "execution_id": "abc123"
}
```

---

### POST /api/search-queues/{id}/pause

**Description:** Pause queue execution

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Search queue paused"
}
```

---

### POST /api/search-queues/{id}/resume

**Description:** Resume paused queue

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "success": true,
  "message": "Search queue resumed"
}
```

---

## Search History Endpoints

### GET /api/search-history/

**Description:** Get search execution history

**Headers:** `Authorization: Bearer <token>`

**Query Parameters:**
- `queue_id` (optional): Filter by queue
- `status` (optional): Filter by status (success, failed, partial)
- `limit` (optional, default: 50): Number of results
- `offset` (optional, default: 0): Pagination offset

**Response:** `200 OK`
```json
{
  "items": [
    {
      "id": 1,
      "queue_id": 1,
      "queue_name": "Missing Episodes - Daily",
      "status": "success",
      "items_processed": 20,
      "items_found": 15,
      "downloads_triggered": 12,
      "started_at": "2026-02-24T02:00:00Z",
      "completed_at": "2026-02-24T02:05:30Z",
      "duration_seconds": 330
    }
  ],
  "total": 100,
  "limit": 50,
  "offset": 0
}
```

---

## Dashboard Endpoints

### GET /api/dashboard/stats

**Description:** Get dashboard statistics

**Headers:** `Authorization: Bearer <token>`

**Response:** `200 OK`
```json
{
  "instances": {
    "total": 2,
    "active": 2,
    "sonarr": 1,
    "radarr": 1
  },
  "queues": {
    "total": 3,
    "active": 2,
    "idle": 1,
    "running": 1
  },
  "searches": {
    "today": 5,
    "week": 35,
    "month": 150,
    "success_rate": 92.5
  }
}
```

---

### GET /api/dashboard/activity

**Description:** Get recent activity

**Headers:** `Authorization: Bearer <token>`

**Query Parameters:**
- `limit` (optional, default: 10): Number of activities

**Response:** `200 OK`
```json
{
  "activities": [
    {
      "type": "search_completed",
      "queue_name": "Missing Episodes - Daily",
      "status": "success",
      "items_found": 15,
      "timestamp": "2026-02-24T02:05:30Z"
    },
    {
      "type": "instance_added",
      "instance_name": "Main Sonarr",
      "timestamp": "2026-02-24T12:00:00Z"
    }
  ]
}
```

---

## Health & Status

### GET /api/health

**Description:** Application health check (no auth required)

**Response:** `200 OK`
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "database": "connected",
  "uptime_seconds": 3600
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Instance name already exists"
}
```

### 401 Unauthorized
```json
{
  "detail": "Invalid authentication credentials"
}
```

### 403 Forbidden
```json
{
  "detail": "Not enough permissions"
}
```

### 404 Not Found
```json
{
  "detail": "Instance not found"
}
```

### 422 Validation Error
```json
{
  "detail": [
    {
      "loc": ["body", "password"],
      "msg": "Password must be at least 8 characters",
      "type": "value_error"
    }
  ]
}
```

### 429 Too Many Requests
```json
{
  "detail": "Rate limit exceeded"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Internal server error"
}
```

---

## Rate Limiting

All endpoints are rate-limited. Response headers include:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1614556800
```

---

## OpenAPI / Swagger

Interactive API documentation available at:
- **Swagger UI:** http://localhost:7337/docs
- **ReDoc:** http://localhost:7337/redoc
- **OpenAPI JSON:** http://localhost:7337/openapi.json

---

**Version:** 0.1.0
**Last Updated:** 2026-02-24
