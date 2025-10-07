
'use strict';

const path = require('path');
const express = require('express');
const morgan = require('morgan');
const dotenv = require('dotenv');

const { createEmergencyRouter } = require('./emergency_webhook');

const app = express();

// Basic permissive CORS (dev). Adjust origins in production.
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(204);
  }
  next();
});
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
