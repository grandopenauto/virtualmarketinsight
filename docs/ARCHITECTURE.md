# VirtualMarketInsight vNext — architecture checkpoint

## Position

VMI is the primary market / capital / opportunity front door. It reconciles the original virtualized financial-market concept with the newer HDP execution infrastructure.

The public experience should answer, in sequence: what is happening; why it matters; what opportunity may exist; what it requires; what capital and capabilities are available; what is missing; what should happen next; and what evidence supports the result.

## Core graph

Opportunity · Requirement · Capability · Resource · Organization · Capital Mandate · Project · Evidence · System · Transaction

`Opportunity → Requirements → Capabilities → Capital → Project → Execution`

## System roles

| System | Primary VMI role |
|---|---|
| VMI | Understand intent; present market, capital, opportunity and execution picture |
| MoneyDragon | Capital intelligence / mandate context |
| Shebavonova | Execution decomposition and orchestration |
| OIE | Opportunity scoring, evidence and thesis validation |
| Digital Cross Dock | Information and evidence interchange |
| Enterprise Systems Factory | Build/integrate missing capability |
| Specialized BOS / agents | Perform specialized operating work |
| Highest Degree Priorities | Company and operating infrastructure underneath |

## Public/private boundary

GitHub Pages is disposable/public presentation. The public VMI API should expose only explicit contracts. Never place master credentials, private customer data, unrestricted VPSBridge access, internal agent source-of-truth data, arbitrary command execution or approval bypasses in the browser/public repository.

## Capital governance

VMI, MoneyDragon and Shebavonova may analyze, model, recommend, orchestrate and prepare next actions. Outside investor funds, securities activity, custody, discretionary asset management or regulated investment activity requires the applicable legal structure, mandate, permissions, approvals and professional/regulatory requirements.

## First implementation boundary

This repository establishes public positioning, responsive front end, shared graph vocabulary, a thin API contract skeleton and static deployment files. It does not claim live market data, live trading, automated investment authority or unrestricted internal-system connectivity.
