
'use strict';

const path = require('path');
const express = require('express');
const morgan = require('morgan');
const dotenv = require('dotenv');

const { createEmergencyRouter } = require('./emergency_webhook');

const app = express();
dotenv.config({ path: path.resolve(__dirname, '.env') });

app.use(morgan('tiny'));
app.get('/', (_req, res) => {
  res.json({ status: 'GuardianAI emergency webhook ready' });
});

app.use(createEmergencyRouter());

const port = process.env.PORT || 4000;
app.listen(port, () => {
  console.log(`GuardianAI emergency webhook listening on port ${port}`);
});
