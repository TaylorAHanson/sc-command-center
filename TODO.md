# Widget Architecture Migration Plan

## Phase 1: Database Migration
- [ ] Design database schema for all widgets (currently in `widgetRegistry.ts`)
- [ ] **[Enhancement]** Add schema support for widget versioning (e.g., semantic versions or incremental IDs). No widget is ever deleted, only deprecated.
- [ ] Create API endpoints for CRUD operations on core widgets
- [ ] Create a seeder to populate the database with the core widgets
- [ ] Remove hardcoded `widgetRegistry` definitions

## Phase 2: Dynamic Loading
- [ ] Update `widgetRegistry` loader to fetch all widgets (core + custom) from the database on startup

## Phase 3: Domains and Roles - Concepts and Structure
** CORE IDEA ** c
- There is an "Domain" selector in the top bar. Users must be in a admin-page configurable role to access a domain.
- Each widget is "domain scoped" to a domain.
- Widgets can be promoted from "domain scoped dev" to "domain scoped test" by people with certain roles.
- Widgets can be promoted from "domain scoped test" to "domain scoped prod" by people with certain roles.
- Widgets can be demoted from "domain scoped prod" to "enterprise" by people with certain roles.
- The enterprise widgets are available to all users in prod regardless of roles/domain.
- The difference visually is that the enterprise widgets are "certified" (already a concept in the UI and widgetRegistry)

** ACTIONS **
- [ ] Convert the concept of Domains to be dynamic and database driven
- [ ] Implement a role based access control system
    - [ ] Roles names and user to role mapping is managed externally (ldap, n2k, qgroups)
    - [ ] Admins: Full access - can configure the role name for each domain (e.g. supplychain-contributor maps to ldap group "sc-grp-dev")
    - [ ] supplychain-contributor: Perform dev to test promotions
    - [ ] supplychain-manager: Perform test to prod promotions
    - [ ] enterprise-manager: Perform prod to enterprise promotions
    - [ ] (and so on for sales, finance, etc)

## Phase 4: Domains and Roles - Environment Promotion
- [ ] 'dev', 'test', and 'prod' are fully separate databases schemas in separate lakebase instances.
- [ ] Implement an API to transfer widget records from one environment to another
- [ ] Update Admin Dashboard UI with a "Widget Management" tab
    - [ ] Based on role, allow users to promote widgets to the next environment
    - [ ] Add ability to "rollback" a widget to a previously known working version in a specific environment.
    - [ ] Based on role, allow users to modify widget definitions (this just launches the widget studio)
    - [ ] Note, domain prod to enterprise is not a move to another database (another environment) but rather setting the 'certified' flag on the widget record in the prod database.
