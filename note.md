
 # secured link with cloudfront(but not working properly):
    https://d2h2xplm1feih8.cloudfront.net

 # working link
    http://cloudmart-env.eba-wbku2kbr.us-east-1.elasticbeanstalk.com/index.html

# To SQL query:

    eb ssh cloudmart-env or eb ssh cloudmart-env --region us-east-1

    psql -h cloudmart-db.c47c866kgmgc.us-east-1.rds.amazonaws.com -U ebuser -d campus_marketplace 

 # to deploy to the existing environment (cloudmart-env):
 eb deploy cloudmart-env --region us-east-1
  
