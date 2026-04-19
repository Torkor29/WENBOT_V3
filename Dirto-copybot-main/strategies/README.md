# Strategies – Developer Guide

This directory contains autonomous strategy pods. Each strategy analyses
market data and publishes **signals** to Redis; it never places orders or
touches user wallets directly.

---

## Creating a new strategy

1. Create a directory under `strategies/` with a descriptive name:

   ```
   strategies/
     my_new_strategy/
       main.py           # entry-point
       requirements.txt   # extra pip dependencies (if any)
   ```

2. Implement an async loop in `main.py` that:
   - Connects to Redis using `shared.config.REDIS_URL`.
   - Performs your market analysis.
   - Publishes signals on the channel `signals:<strategy_id>`.
   - Sleeps or awaits the next trigger.

3. Use the entry-point pattern:

   ```python
   if __name__ == "__main__":
       asyncio.run(main())
   ```

4. Look at `strategies/example_strategy/main.py` for a minimal working
   example.

---

## Redis signal format

Every signal is a JSON object published via `PUBLISH` on:

```
signals:{strategy_id}
```

### Required fields

| Field          | Type    | Description                                       |
| -------------- | ------- | ------------------------------------------------- |
| `strategy_id`  | string  | Unique identifier of the strategy (e.g. `strat_example_v1`). |
| `action`       | string  | `"BUY"` (only supported action for now).          |
| `side`         | string  | `"YES"` or `"NO"` – the outcome side to buy.      |
| `market_slug`  | string  | Polymarket market slug.                            |
| `token_id`     | string  | Polymarket CLOB token ID for the chosen side.      |
| `max_price`    | float   | Maximum price (0-1) the strategy is willing to pay. |
| `timestamp`    | float   | Unix epoch (seconds) when the signal was generated. |

### Optional fields

| Field        | Type  | Description                                  |
| ------------ | ----- | -------------------------------------------- |
| `confidence` | float | Strategy confidence score (0.0 – 1.0).       |

### Example payload

```json
{
  "strategy_id": "strat_example_v1",
  "action": "BUY",
  "side": "YES",
  "market_slug": "btc-updown-5m-example",
  "token_id": "example_token_id_placeholder",
  "max_price": 0.55,
  "confidence": 0.82,
  "timestamp": 1711300000.123
}
```

---

## What a strategy must NOT do

- **Access user wallets or private keys.** Strategies have no access to
  `WENBOT_PRIVATE_KEY`, `ENCRYPTION_MASTER_KEY`, or any user-specific secrets.
- **Place orders directly on Polymarket.** Order execution is handled
  exclusively by the executor service.
- **Read Kubernetes secrets or environment variables that belong to other
  services.** Each strategy pod runs in its own isolated container.
- **Modify the database.** Strategies are read-only consumers of market data;
  all writes go through the executor or API.

---

## Testing locally

1. Make sure Redis is running (via the project's `docker-compose`):

   ```bash
   docker-compose up -d redis
   ```

2. Set the `REDIS_URL` environment variable (defaults to
   `redis://localhost:6379`):

   ```bash
   export REDIS_URL=redis://localhost:6379
   ```

3. Run the strategy directly:

   ```bash
   python -m strategies.example_strategy.main
   ```

4. In another terminal, subscribe to the channel to see the signals:

   ```bash
   redis-cli SUBSCRIBE signals:strat_example_v1
   ```

---

## Deploying

Use the deployment script at the project root:

```bash
./deploy_strategy.sh <strategy_directory_name>
```

The script builds the Docker image, pushes it to the container registry, and
updates the Kubernetes deployment. Refer to `deploy_strategy.sh` for available
flags and options.
