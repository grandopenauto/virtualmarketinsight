# Project RipFest

**Product name:** VMI Collectibles Market Intelligence  
**Internal codename:** Project RipFest  
**Parent system:** Virtual Market Insight (VMI)

## Mission

Build the private demand, buy-box, pricing and transaction network first. Livestreaming, eBay, Fanatics/Whatnot-style distribution and other external rails are optional downstream channels rather than the foundation of the system.

The core objective is to know, before inventory is acquired or publicly auctioned:

- who buys the asset class,
- what they are willing to buy,
- under what condition/grade/era constraints,
- at what percentage of market value or absolute price,
- how much capacity they have,
- whether an explicit executable offer already exists.

## Core transaction graph

Dealer / Collector
→ Buy Box
→ Asset
→ Market Evidence
→ Match
→ Executable Quote
→ Transaction
→ Commercial Memory

The system should eventually support the reverse direction as well:

Inventory / Collection
→ break into assets or lots
→ identify matching buy boxes
→ solicit bids
→ establish liquidity floor
→ decide consign / buy / grade / vault / auction / livestream

## Phase 1 — Private Market Foundation

Implemented in the `project-ripfest` branch:

- `api/ripfest.py`
  - SQLite-backed dealer registry
  - buy-box registry
  - asset registry
  - explicit quote ledger
  - deterministic buy-box matching
  - transaction-readiness classification
  - all private data protected by `VMI_OPERATOR_KEY`
- `api/ripfest_service.py`
  - standalone FastAPI service
  - can be deployed separately before integration into the primary VMI gateway

### Current API surface

Public-safe:

- `GET /`
- `GET /health`
- `GET /api/v1/collectibles/status`

Operator-gated:

- `GET /api/v1/operator/collectibles/summary`
- `POST /api/v1/operator/collectibles/dealers`
- `GET /api/v1/operator/collectibles/dealers`
- `POST /api/v1/operator/collectibles/buy-boxes`
- `GET /api/v1/operator/collectibles/buy-boxes`
- `POST /api/v1/operator/collectibles/assets`
- `GET /api/v1/operator/collectibles/assets`
- `POST /api/v1/operator/collectibles/quotes`
- `POST /api/v1/operator/collectibles/match`

No endpoint currently places bids, purchases inventory, moves money, or contacts a dealer automatically.

## Phase 2 — Dealer / Hobby-Shop Acquisition

Use existing HDP systems rather than create a new outreach stack:

1. **LinkStream / discovery**
   - find hobby shops, card stores, breakers, consignors and high-volume collectors.
2. **CCAO**
   - map the transaction graph and determine the smallest useful ask.
3. **Lead Wizard / Email / LinkedIn / Voice**
   - contact the business and collect buying criteria.
4. **Digital Cross Dock**
   - normalize responses into VMI Collectibles buy-box records.
5. **Commercial Memory**
   - keep actual quotes, declined deals, accepted deals and revised buying criteria.

The initial outreach should lead with value: "What are you actively buying?" rather than asking the store to join a speculative new marketplace.

## Buy-box fields

Minimum useful dealer profile:

- category (Pokemon, sports, MTG, etc.)
- game / league / segment
- sealed vs raw vs graded
- era / year range
- preferred grading company
- minimum grade
- target acquisition percentage of comp
- maximum unit price
- approximate monthly capacity
- named cards / players / characters / sets of interest
- explicit exclusions
- cash / consignment / conditional purchase preference

## Phase 3 — Market Intelligence

Add evidence adapters without making any one marketplace a dependency:

- observed listings
- observed auctions
- dealer quotes
- public comps where lawfully/contractually available
- grading populations and grading cost/time
- collection inventories
- livestream realized prices
- our own completed transactions

Every observation should be timestamped and source-labeled.

External marketplaces such as eBay can be used as sensors and optional execution rails, but the private buy-box network remains the durable asset.

## Phase 4 — Asset Routing / Liquidity Stack

When an asset enters the system:

1. identify / normalize the asset,
2. estimate market range,
3. query private buy boxes,
4. determine dealer depth,
5. request explicit quotes from top matches,
6. display executable cash bids separately from estimated value,
7. route to the best approved transaction path.

Example desired output:

- estimated market range: $9,800–$10,600
- 14 matching buyer profiles
- 5 buyers requested for quote
- best executable cash quote: $8,400
- grading: recommended / not recommended
- recommended route: sell now / grade / consign / auction / hold

## Phase 5 — Grading / Vault / Inventory

Grading should become part of market infrastructure, not merely a perk.

Potential model:

- complimentary or subsidized grading above a value threshold,
- grading subsidized when the asset remains in the VMI/RipFest vault or marketplace,
- track raw → graded value uplift and realized ROI,
- preserve chain-of-custody and certification metadata.

## Phase 6 — Livestream Market

Launch livestreaming only after the private network demonstrates real liquidity.

A reveal should be able to trigger:

Reveal
→ identify asset
→ update collection ledger
→ query buy boxes
→ request/refresh dealer quotes
→ show estimated value separately from executable offers
→ Keep / Grade / Sell Now / Auction / Vault

The host is the entertainment/community layer. The network and executable demand are the credibility layer.

## Phase 7 — Collection Ledger / RipFest

For finite, inventoried collections:

- original item count,
- remaining item count,
- known premium items remaining,
- revealed inventory,
- realized prices,
- outstanding dealer demand,
- remaining estimated value,
- bidder depth,
- liquidity score.

This creates a market whose state changes after every reveal.

## Phase 8 — Larger Collection Acquisition

Do not begin by financing a $15M collection and hoping demand appears.

Build demonstrated absorption capacity first:

private buyers
→ recurring quotes
→ completed transactions
→ stronger consignments
→ larger inventory pools
→ deeper liquidity
→ institutional / large-collector participation
→ major collection consignments or acquisitions

The long-term objective is for the network to make a large collection financeable because the likely buyers and their capacity are already known.

## Initial operating metric stack

Track from day one:

- qualified dealers
- active buy boxes
- total indicated monthly buying capacity
- assets routed
- average buyer matches per asset
- explicit quote rate
- best-quote / estimated-value ratio
- quoted-to-closed conversion
- time to first executable quote
- gross merchandise value
- repeat dealer participation
- grading uplift
- inventory days-to-liquidity

## Deployment target

Existing VMI architecture remains the parent:

GitHub Pages VMI
→ `api.virtualmarketinsight.com`
→ VMI gateway / private services
→ Project RipFest / VMI Collectibles
→ existing HDP discovery, acquisition and fulfillment systems

Suggested first standalone service port: `3210` (confirm availability on the VPS before binding).

Example local start command from `C:\HDP\VMI\api`:

```powershell
python -m uvicorn ripfest_service:app --host 127.0.0.1 --port 3210
```

Before production use:

- verify port availability,
- set `VMI_OPERATOR_KEY`,
- set `VMI_COLLECTIBLES_DB` if a dedicated data location is preferred,
- test `/health`,
- test create dealer → create buy box → create asset → match,
- place behind IIS/ARR or route through the existing VMI gateway,
- do not expose operator endpoints publicly without the existing VMI authorization controls.
