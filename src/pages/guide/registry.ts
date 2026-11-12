import type { GuideSection } from './types';
import { section as overview } from './sections/overview';
import { section as quickstart } from './sections/quickstart';
import { section as views } from './sections/views';
import { section as discover } from './sections/discover';
import { section as widgets } from './sections/widgets';
import { section as schedules } from './sections/schedules';
import { section as assistant } from './sections/assistant';
import { section as widgetStudio } from './sections/widget-studio';
import { section as agentStudio } from './sections/agent-studio';
import { section as sharing } from './sections/sharing';
import { section as publishing } from './sections/publishing';
import { section as access } from './sections/access';
import { section as settings } from './sections/settings';
import { section as migration } from './sections/migration';
import { section as actionLogs } from './sections/action-logs';
import { section as reference } from './sections/reference';
import { section as troubleshooting } from './sections/troubleshooting';

// The order here is the order of the sidebar, within each group.
export const SECTIONS: GuideSection[] = [
  overview,
  quickstart,
  views,
  discover,
  widgets,
  schedules,
  assistant,
  widgetStudio,
  agentStudio,
  sharing,
  publishing,
  access,
  settings,
  migration,
  actionLogs,
  reference,
  troubleshooting,
];
