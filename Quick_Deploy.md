🚀 Quick Deploy Instructions:

Add to /config/secrets.yaml:

yaml   ownerrez_username: "your-email@ownerrez.com"
   ownerrez_token: "pt_your_token_here"

Enable packages in /config/configuration.yaml:

yaml   homeassistant:
     packages: !include_dir_named packages

Create packages folder:

bash   mkdir -p /config/packages

Save the package:

Save the artifact as /config/packages/ownerrez_lock_manager.yaml


Customize these 3 things in the file:

Line 197, 238, 260: Change lock.front_door to your lock entity
Line 200, 241: Change code slot 5 if needed
Lines 165, 211, 250, 279, 306, 327: Change notify.mobile_app to your notification service


Restart Home Assistant

The package is self-contained and won't conflict with existing configurations. All entities are prefixed with ownerrez_ to avoid naming conflicts.
Ready to deploy! 🎉
