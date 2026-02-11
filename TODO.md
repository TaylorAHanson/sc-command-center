# TODO		

## Visual Changes
    - [x] Change the word "Dashboard" wherever it appears to something else that reflects the true nature of the app. 
    - [x] Add a 'w' to open widgets
    - [x] Add second order of organization to widgets (by business domain for starters, but generalize so the owners of this app can change their mind)
    - [x] Add search to the widget library. Allow searching on both title and description
    - [x] To the widget library header, add a toggle that shows only the widgets the user has access to run or all widgets. Mock a few widgets that the user doesn't have access to run, and overlay with a 'request access button' that links to our self service hub
    - [x] To all widgets, add a popularity score.
        - [x] Add an API endpoint and a table that stores the amount of times a widget is run. This counter becomes the popularity score.
        - [x] Design this in a way that we can easily add other factors to the score later (e.g. data freshness, user ratings, etc.)
        - [x] Add a simple sqllite implemenation to store this, with the framework in place to switch to Databricks Lakebase (postgresql) later
    - [x] To the widget library header, add a toggle that shows all widgets, or only "certified" widgets. Add an icon to the widgets once on a dashboard to indicate whether or not it is certified at a glance.
    - [x] Introduce a Configurable widget concept. There are 3 modes, set in the property 'configurable_mode'
        - [x] 'config_required': The user must configure the widget before it can be added to the dashboard. When dragging/dropping, a modal pops up with the configuration options. The user can change this config later by clicking the gear icon near the fullscreen icon.
        - [x] 'config_allowed': The widget is added without delay, but the user can click a gear icon near the fullscreen icon to edit the values later
        - [x] 'none': No configuration options are available to the user, either on add or via click of gear icon.
        - [x] This config must be persisted in local storage alongside the view config.
    - [x] To the lower portion of the left nav, add 2 links:
        - [x] A link to the documentation
        - [x] A link to the self service hub
        - [x] Report Issue
    - [x] Add a gallery vs list view toggle to the widget library

## App Architecture
    - [x] For any 'executable' action that the user takes, log it to the database. see @readme.md for more info on why we want to do this.
        - [x] What was the user looking at? For all visible widgets, log the widget name, widget id, widget configuration, etc.
        - [x] What did the user do? Which 'executable' widget did they interact with? Log the same info for this
        - [x] To facilitate this, we need to add a flag to the widget registry to indicate whether a widget is 'executable' or not. 
        - [x] Pop up a window to confirm the action, ask the user to briefly explain why they are taking this action, and then log it to the database. 
        - [x] All of this should be one row, that can be used for ML training according to the goals outlined in @readme.md.
    - [x] Add an admin panel
        - [x] Add a way to view logged data from executable actions

## Widgets
    - [x] Bring over changes for SQL runner
    - [x] Bring over changes for Genie runner
    - [x] Bring over changes for Notebook runner
    - [x] N8N - Have a widget that can trigger a workflow
    - [x] Tableau - Add tableau widget that can display a tableau dashboard. 
        - [ ] PLT Metric: Demand Coverage / Plan solve health



- [ ] Default to category view in widget library. Change the order - 
- [ ] "My Access Only" - default to 'on' - "Accessible to Me" "No Request Needed" include "not accessible to me"
- [ ] Default the thumbnails
- [ ] Generic iframe widget with dbl click to open full size 

- [ ] Widget Studio
- [ ] exit admin panel