   ..        .....        ...       
   ....     ......       ....      
   .......... ...       .....       
   ........    ..      ......       
   ......      ..     .......       
   .....       ...  .........       
   ....        .....     ....      
   ...         ....        ..   


    N A T A K   -   Nucleus V1         
                                      
      Mesh Networking Radio           


# Install apt packages
sudo apt update && sudo apt install -y hostapd babeld smcroute tcpdump nftables python3 python3-pip aircrack-ng iperf3 ufw 
# Install Reticulum (must start rns/rnsd at least once to generate config)
pip3 install --break-system-packages --upgrade rns lxmf flask pytap2 meshtastic[cli]
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

