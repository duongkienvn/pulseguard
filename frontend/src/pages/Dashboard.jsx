import React, { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Navigate } from 'react-router-dom';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import { LogOut, Activity, HardDrive, Cpu, Network } from 'lucide-react';

const Dashboard = () => {
    const { user, logout, tokens } = useAuth();
    const [metrics, setMetrics] = useState(null);
    const [history, setHistory] = useState([]);

    // Redirect to agents page - the new default view
    if (user) {
        return <Navigate to="/agents" replace />;
    }

    useEffect(() => {
        if (!user || !tokens?.access_token) return;
        
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws?token=${tokens.access_token}`);

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                setMetrics(data);
                setHistory(prev => {
                    // Flatten the data for Recharts (it doesn't handle nested keys well)
                    const flatData = {
                        time: new Date(data.timestamp * 1000).toLocaleTimeString(),
                        cpuUsage: data.cpu.usage_percent,
                        memoryUsage: data.memory.used_percent,
                    };
                    const newHistory = [...prev, flatData];
                    return newHistory.slice(-30); // Keep last 30 points
                });
            } catch (e) {
                console.error("Error parsing WS message", e);
            }
        };

        return () => {
            ws.close();
        };
    }, [user]);

    if (!metrics) return <div className="min-h-screen flex items-center justify-center">Loading metrics...</div>;

    const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042'];

    return (
        <div className="min-h-screen bg-gray-50">
            <nav className="bg-white shadow-sm">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
                    <div className="flex justify-between h-16">
                        <div className="flex items-center">
                            <Activity className="h-8 w-8 text-indigo-600" />
                            <span className="ml-2 text-xl font-bold text-gray-900">StatusMonitor</span>
                        </div>
                        <div className="flex items-center">
                            <span className="mr-4 text-gray-700">Welcome, {user?.username}</span>
                            <button
                                onClick={logout}
                                className="inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
                            >
                                <LogOut className="h-4 w-4 mr-2" />
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            </nav>

            <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
                <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4 mb-8">
                    {/* Summary Cards */}
                    <div className="bg-white overflow-hidden shadow rounded-lg">
                        <div className="p-5">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <Cpu className="h-6 w-6 text-gray-400" />
                                </div>
                                <div className="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt className="text-sm font-medium text-gray-500 truncate">CPU Usage</dt>
                                        <dd className="text-lg font-medium text-gray-900">{metrics.cpu.usage_percent}%</dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div className="bg-white overflow-hidden shadow rounded-lg">
                        <div className="p-5">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <Activity className="h-6 w-6 text-gray-400" />
                                </div>
                                <div className="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt className="text-sm font-medium text-gray-500 truncate">Memory Usage</dt>
                                        <dd className="text-lg font-medium text-gray-900">{metrics.memory.used_percent}%</dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div className="bg-white overflow-hidden shadow rounded-lg">
                        <div className="p-5">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <HardDrive className="h-6 w-6 text-gray-400" />
                                </div>
                                <div className="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt className="text-sm font-medium text-gray-500 truncate">Disk Usage (C:)</dt>
                                        <dd className="text-lg font-medium text-gray-900">
                                            {metrics.disk.partitions.find(p => p.mountpoint === 'C:\\')?.percent}%
                                        </dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div className="bg-white overflow-hidden shadow rounded-lg">
                        <div className="p-5">
                            <div className="flex items-center">
                                <div className="flex-shrink-0">
                                    <Network className="h-6 w-6 text-gray-400" />
                                </div>
                                <div className="ml-5 w-0 flex-1">
                                    <dl>
                                        <dt className="text-sm font-medium text-gray-500 truncate">Network Sent</dt>
                                        <dd className="text-lg font-medium text-gray-900">{(metrics.network.bytes_sent / 1024 / 1024).toFixed(2)} MB</dd>
                                    </dl>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                    {/* CPU History Chart */}
                    <div className="bg-white shadow rounded-lg p-6">
                        <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">CPU History</h3>
                        <div className="h-64">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={history}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis 
                                        dataKey="time" 
                                        tick={{ fontSize: 11 }}
                                        interval="preserveStartEnd"
                                    />
                                    <YAxis 
                                        domain={[0, 100]} 
                                        tickFormatter={(value) => `${value}%`}
                                    />
                                    <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, 'CPU']} />
                                    <Legend />
                                    <Line 
                                        type="monotone" 
                                        dataKey="cpuUsage" 
                                        stroke="#8884d8" 
                                        name="CPU %" 
                                        dot={false}
                                        isAnimationActive={false}
                                        strokeWidth={2}
                                    />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    </div>

                    {/* Memory History Chart */}
                    <div className="bg-white shadow rounded-lg p-6">
                        <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">Memory History</h3>
                        <div className="h-64">
                            <ResponsiveContainer width="100%" height="100%">
                                <LineChart data={history}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis 
                                        dataKey="time" 
                                        tick={{ fontSize: 11 }}
                                        interval="preserveStartEnd"
                                    />
                                    <YAxis 
                                        domain={[0, 100]} 
                                        tickFormatter={(value) => `${value}%`}
                                    />
                                    <Tooltip formatter={(value) => [`${value.toFixed(1)}%`, 'Memory']} />
                                    <Legend />
                                    <Line 
                                        type="monotone" 
                                        dataKey="memoryUsage" 
                                        stroke="#82ca9d" 
                                        name="Mem %" 
                                        dot={false}
                                        isAnimationActive={false}
                                        strokeWidth={2}
                                    />
                                </LineChart>
                            </ResponsiveContainer>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
};

export default Dashboard;
