const express = require('express');
const basicAuth = require('express-basic-auth');
const AWS = require('aws-sdk');
const { Client } = require('pg');
const path = require('path');
const moment = require('moment');

require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

// Configure AWS SDK
AWS.config.update({
    region: 'us-east-1'
});

const cloudwatch = new AWS.CloudWatchLogs();
const ecs = new AWS.ECS();
const ssm = new AWS.SSM();

// Basic authentication middleware
app.use(basicAuth({
    users: { 'admin': process.env.ADMIN_PASSWORD || 'imobiliare2024' },
    challenge: true,
    realm: 'Imobiliare Scraper Monitoring'
}));

// Set up EJS template engine
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(express.static(path.join(__dirname, 'public')));

// Database connection
let pgClient = null;

async function getDbConnection() {
    if (!pgClient) {
        const dbConnString = await getParameterValue('/HomeAiScrapper/DB_CONNECTION_STRING');
        pgClient = new Client({
            connectionString: dbConnString
        });
        await pgClient.connect();
    }
    return pgClient;
}

async function getParameterValue(paramName) {
    try {
        const response = await ssm.getParameter({
            Name: paramName,
            WithDecryption: true
        }).promise();
        return response.Parameter.Value;
    } catch (error) {
        console.error(`Failed to get parameter ${paramName}:`, error);
        return process.env[paramName.split('/').pop()] || '';
    }
}

// Routes
app.get('/', async (req, res) => {
    try {
        const [taskRuns, recentLogs, scrapedCount, priceDrops] = await Promise.all([
            getRecentTaskRuns(),
            getRecentLogs(),
            getScrapedPropertiesCount(),
            getTopPriceDrops()
        ]);

        res.render('dashboard', {
            taskRuns,
            recentLogs,
            scrapedCount,
            priceDrops,
            moment
        });
    } catch (error) {
        console.error('Error loading dashboard:', error);
        res.status(500).send('Error loading dashboard');
    }
});

async function getRecentTaskRuns() {
    try {
        const response = await ecs.listTasks({
            cluster: 'homeai-ecs-cluster',
            family: 'imobiliare-scraper-task',
            maxResults: 10,
            desiredStatus: 'STOPPED'
        }).promise();

        if (response.taskArns.length === 0) {
            return [];
        }

        const tasksDetail = await ecs.describeTasks({
            cluster: 'homeai-ecs-cluster',
            tasks: response.taskArns
        }).promise();

        return tasksDetail.tasks.map(task => ({
            taskArn: task.taskArn,
            taskId: task.taskArn.split('/').pop(),
            status: task.lastStatus,
            startedAt: task.startedAt,
            stoppedAt: task.stoppedAt,
            stoppedReason: task.stoppedReason || 'N/A',
            cpu: task.cpu,
            memory: task.memory
        }));
    } catch (error) {
        console.error('Error fetching task runs:', error);
        return [];
    }
}

async function getRecentLogs(limit = 20) {
    try {
        const streams = await cloudwatch.describeLogStreams({
            logGroupName: '/ecs/imobiliare-scraper',
            orderBy: 'LastEventTime',
            descending: true,
            limit: 5
        }).promise();

        if (!streams.logStreams || streams.logStreams.length === 0) {
            return [];
        }

        const logs = [];
        for (const stream of streams.logStreams.slice(0, 2)) {
            const events = await cloudwatch.getLogEvents({
                logGroupName: '/ecs/imobiliare-scraper',
                logStreamName: stream.logStreamName,
                startFromHead: false,
                limit: limit / 2
            }).promise();

            logs.push(...events.events.map(event => ({
                timestamp: new Date(event.timestamp),
                message: event.message,
                stream: stream.logStreamName
            })));
        }

        return logs.sort((a, b) => b.timestamp - a.timestamp).slice(0, limit);
    } catch (error) {
        console.error('Error fetching logs:', error);
        return [];
    }
}

async function getScrapedPropertiesCount() {
    try {
        const db = await getDbConnection();
        const result = await db.query(`
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN created_date >= NOW() - INTERVAL '24 hours' THEN 1 END) as last_24h,
                COUNT(CASE WHEN created_date >= NOW() - INTERVAL '7 days' THEN 1 END) as last_7d
            FROM properties_romania
        `);
        return result.rows[0];
    } catch (error) {
        console.error('Error fetching property count:', error);
        return { total: 0, last_24h: 0, last_7d: 0 };
    }
}

async function getTopPriceDrops() {
    try {
        const db = await getDbConnection();
        const result = await db.query(`
            WITH price_history AS (
                SELECT
                    url,
                    title,
                    address,
                    price_ron,
                    created_date,
                    LAG(price_ron) OVER (PARTITION BY url ORDER BY created_date) as previous_price
                FROM properties_romania
                WHERE created_date >= NOW() - INTERVAL '2 months'
            ),
            price_changes AS (
                SELECT
                    url,
                    MAX(title) as title,
                    MAX(address) as address,
                    MIN(price_ron) as current_price,
                    MAX(previous_price) as highest_price,
                    MAX(previous_price) - MIN(price_ron) as price_drop,
                    ROUND(((MAX(previous_price) - MIN(price_ron))::numeric / NULLIF(MAX(previous_price), 0)) * 100, 2) as drop_percentage
                FROM price_history
                WHERE previous_price IS NOT NULL
                    AND previous_price > price_ron
                GROUP BY url
            )
            SELECT *
            FROM price_changes
            WHERE price_drop > 0
            ORDER BY drop_percentage DESC
            LIMIT 100
        `);
        return result.rows;
    } catch (error) {
        console.error('Error fetching price drops:', error);
        return [];
    }
}

// API endpoints for AJAX updates
app.get('/api/logs', async (req, res) => {
    const logs = await getRecentLogs();
    res.json(logs);
});

app.get('/api/stats', async (req, res) => {
    const stats = await getScrapedPropertiesCount();
    res.json(stats);
});

app.get('/api/price-drops', async (req, res) => {
    const drops = await getTopPriceDrops();
    res.json(drops);
});

// Start server
app.listen(PORT, () => {
    console.log(`Monitoring dashboard running on port ${PORT}`);
    console.log(`Access at: http://localhost:${PORT}`);
});