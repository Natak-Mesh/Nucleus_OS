# TAK Server Setup: Database and Java 17

### 1. Install PostgreSQL
sudo apt update
sudo apt install -y postgresql

### 2. Add Adoptium (Temurin) Repository Keys
sudo wget -O - https://packages.adoptium.net/artifactory/api/gpg/key/public | sudo gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg

### 3. Add the Java Repository
echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb bookworm main" | sudo tee /etc/apt/sources.list.d/adoptium.list

### 4. Install Temurin Java 17
sudo apt update
sudo apt install -y temurin-17-jdk
