import re
with open('src/store/dashboardStore.tsx', 'r') as f:
    content = f.read()

print("Provider Export:", bool(re.search(r'export\s+const\s+DashboardProvider', content)))
print("Context Create:", bool(re.search(r'createContext', content)))
print("Provider Return:", bool(re.search(r'<DashboardContext\.Provider', content)))
