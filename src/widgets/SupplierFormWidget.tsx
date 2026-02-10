import React from 'react';
import { Model } from 'survey-core';
import { Survey } from 'survey-react-ui';
import 'survey-core/survey-core.min.css';
import type { WidgetProps } from '../widgetRegistry';

const surveyJson = {
  elements: [{
    name: "SupplierRating",
    title: "Rate the recent delivery from Supplier X:",
    type: "rating",
    rateMax: 5
  }, {
    name: "Comments",
    title: "Additional Feedback",
    type: "comment"
  }]
};

export const SupplierFormWidget: React.FC<WidgetProps> = () => {
  const model = new Model(surveyJson);
  
  // Apply some basic styling through survey-core theme API or CSS overrides if needed
  // For now, defaultV2 theme is used which is clean.

  return (
    <div className="h-full overflow-y-auto">
      <Survey model={model} />
    </div>
  );
};

