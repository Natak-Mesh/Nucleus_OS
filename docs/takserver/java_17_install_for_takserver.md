# Installing Java 17 on Raspberry Pi OS (Debian Trixie)

Debian Trixie removed OpenJDK 17 from its repositories.  
To install Java 17 safely, pull it from Debian Bookworm and pin it so the rest of the system is unaffected.

## Add APT Pin for Bookworm
```bash
echo -e "Package: *\nPin: release n=bookworm\nPin-Priority: 100" | \
sudo tee /etc/apt/preferences.d/bookworm

#add bookworm repo
echo "deb http://deb.debian.org/debian bookworm main" | \
sudo tee /etc/apt/sources.list.d/bookworm.list


#update and install openjdk 17
sudo apt update
sudo apt install openjdk-17-jre
