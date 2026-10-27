# RESQNET — Backend & Coordination Engine

## Overview
The RESQNET backend serves as the communication layer between the mission-control frontend, disaster scenario data, drone coordination logic, and computer-vision module. It is designed to support reliable information exchange and decentralized task coordination during disaster-response simulations.

## Core Responsibilities
- Provide API endpoints for disaster scenarios and mission information.
- Process drone task assignments, search progress, and task status updates.
- Receive person-detection results from the computer-vision module.
- Associate detection evidence with the corresponding drone and disaster-affected area.
- Calculate area priorities using detection evidence, scenario priority, deadlines, and search progress.
- Support task reassignment and state synchronization during communication failures.

## Technology Stack
- Python
- FastAPI for REST API development
- JSON for scenario and task data
- Integration with the RESQNET frontend and computer-vision module

## System Workflow
1. Receive scenario and mission requests from the frontend.
2. Load and process disaster scenario information.
3. Receive detection results containing bounding boxes and confidence scores.
4. Update relevant area information and calculate priority scores.
5. Return updated task and priority information to the mission-control dashboard.

## Decentralized Coordination
The backend coordination logic is intended to help the system recover unfinished tasks when communication with a central controller is interrupted. Drones can use locally available information to support continued search operations, with synchronization performed when communication becomes available.

## Objective
Develop a modular backend that connects perception, prioritization, and drone coordination into a resilient disaster-response simulation.

## Development Status
API endpoints, task coordination, and computer-vision integration should be documented according to their implementation and testing status. Planned capabilities are not considered operational until verified.
