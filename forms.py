from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Length

class PublicationForm(FlaskForm):
    titre = StringField('Titre', validators=[DataRequired(), Length(max=100)])
    contenu = TextAreaField('Contenu', validators=[DataRequired()])
    # Champ optionnel pour joindre une photo ou une vidéo
    media = FileField('Média (Photo/Vidéo)', validators=[FileAllowed(['jpg', 'png', 'jpeg', 'mp4', 'mov'], 'Images et vidéos uniquement !')])
    submit = SubmitField('Publier')